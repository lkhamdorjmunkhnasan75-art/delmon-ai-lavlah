"""Restricted HTTPS JSON transport. No redirects, proxies or credentials."""
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from lavlah.ingestion import IngestionError, prepare

MAX_BYTES=512000

def endpoint_parts(url):
    try:
        p=urlsplit(url)
        if (p.scheme!="https" or not p.hostname or p.username or p.password
            or p.fragment or p.port not in (None,443) or p.query
            or not p.hostname.isascii() or p.hostname.endswith(".")
            or any(ord(ch)<33 or ord(ch)>126 for ch in url) or "\\" in url):
            raise ValueError()
        try:
            ipaddress.ip_address(p.hostname)
        except ValueError:
            pass
        else:
            raise ValueError()
        if "." not in p.hostname:
            raise ValueError()
        return p.hostname,p.path or "/"
    except ValueError:
        raise IngestionError("endpoint_invalid") from None

def public_addresses(host, resolver=socket.getaddrinfo):
    answers=resolver(host,443,type=socket.SOCK_STREAM)
    addresses=[]
    for answer in answers:
        ip=ipaddress.ip_address(answer[4][0])
        if (not ip.is_global or ip.is_multicast or ip.is_reserved
            or getattr(ip,"ipv4_mapped",None) or getattr(ip,"scope_id",None)
            or (ip.version==6 and (ip.sixtofour or ip.teredo or any(ip in ipaddress.ip_network(net) for net in ('64:ff9b::/96','64:ff9b:1::/48'))))):
            raise IngestionError("unsafe_address")
        addresses.append(str(ip))
    if not addresses:
        raise IngestionError("unsafe_address")
    return addresses

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,ip):
        super().__init__(host,443,timeout=5,context=ssl.create_default_context())
        self.ip=ip
    def connect(self):
        # Connect to the validated numeric IP, but authenticate the original DNS name.
        family=socket.AF_INET6 if ":" in self.ip else socket.AF_INET
        sock=socket.socket(family,socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.ip,443))
            self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:
            sock.close()
            raise

def fetch_json(url):
    host,path=endpoint_parts(url)
    ip=public_addresses(host)[0]
    connection=PinnedHTTPS(host,ip)
    deadline=time.monotonic()+15
    try:
        connection.request("GET",path,headers={"Accept":"application/json","Accept-Encoding":"identity","User-Agent":"DelmonLavlahAuthorized/0.1"})
        response=connection.getresponse()
        if response.status!=200:
            raise IngestionError("http_status")
        if response.headers.get_content_type()!="application/json" or response.getheader("Content-Encoding","identity").lower()!="identity":
            raise IngestionError("content_type")
        length=response.getheader("Content-Length")
        if length is not None and (not length.isdigit() or int(length)>MAX_BYTES):
            raise IngestionError("body_limit")
        chunks=[]
        size=0
        while True:
            if time.monotonic()>deadline:
                raise IngestionError("timeout")
            chunk=response.read1(min(16384,MAX_BYTES+1-size))
            if not chunk: break
            chunks.append(chunk)
            size+=len(chunk)
            if size>MAX_BYTES: raise IngestionError("body_limit")
        return b"".join(chunks)
    finally:
        connection.close()

def decode_envelope(raw,now,freshness_days):
    if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:
        raise IngestionError("body_limit")
    try:
        obj=json.loads(raw)
        if not isinstance(obj,dict) or set(obj)!={"updated_at","records"}:
            raise ValueError()
        observed=datetime.fromisoformat(obj["updated_at"])
        if observed.tzinfo is None: raise ValueError()
        observed=observed.astimezone(timezone.utc)
        if not now-timedelta(days=freshness_days)<observed<=now:
            raise ValueError()
        records=obj["records"]
        if not isinstance(records,list) or not 1<=len(records)<=100:
            raise ValueError()
        for record in records:
            if not isinstance(record,dict): raise ValueError()
            prepare(record)
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        raise IngestionError("freshness_or_schema_invalid") from None
    return records,observed,hashlib.sha256(raw).hexdigest()

def collect_registered(dsn,permission_id,actor,fetch=None,*,reserve_domain=None,run_id=None):
    """Reserve a request slot durably before network I/O; recheck permission before storing."""
    from contextlib import closing
    from uuid import UUID
    import psycopg
    from psycopg.rows import dict_row
    from lavlah.ingestion import permission, require_actor, strict_connection
    if fetch is None:
        raise IngestionError('Explicit bounded transport required')
    if fetch is fetch_json:
        from lavlah.bounded_transport import bounded_fetch
        fetch=bounded_fetch
    pid,actor=UUID(str(permission_id)),UUID(str(actor))
    with closing(psycopg.connect(dsn,row_factory=dict_row,connect_timeout=5)) as c:
        with c.transaction():
            strict_connection(c,"lavlah_ingest_test")
            c.execute("SET LOCAL ROLE lavlah_ingestion")
            c.execute("SET LOCAL statement_timeout='5s'")
            if run_id is not None:
                active=c.execute("SELECT 1 FROM lavlah.https_scheduler_runs WHERE id=%s AND permission_id=%s AND outcome='running' AND lease_until>clock_timestamp() FOR UPDATE",(run_id,pid)).fetchone()
                if not active: raise IngestionError("lease_expired")
            grant=permission(c,pid)
            require_actor(c,pid,actor,"collect")
            source=c.execute("SELECT * FROM lavlah.https_sources WHERE permission_id=%s AND enabled FOR UPDATE",(pid,)).fetchone()
            if not source or source["endpoint"]!=grant["source_url"]:
                raise IngestionError("endpoint_not_authorized")
            endpoint_parts(source["endpoint"])
            reserved=c.execute("""UPDATE lavlah.https_sources SET next_fetch_at=clock_timestamp()+min_interval_seconds*interval '1 second'
                WHERE permission_id=%s AND next_fetch_at<=clock_timestamp() RETURNING endpoint""",(pid,)).fetchone()
            if not reserved: raise IngestionError("rate_limited")
            endpoint=reserved["endpoint"]
            from lavlah.scheduler import reserve_domain as shared_reservation
            shared_reservation(c,endpoint)
        try:
            raw=fetch(endpoint)
            with c.transaction():
                c.execute("SET LOCAL ROLE lavlah_ingestion")
                if run_id is not None:
                    active=c.execute("SELECT 1 FROM lavlah.https_scheduler_runs WHERE id=%s AND permission_id=%s AND outcome='running' AND lease_until>clock_timestamp() FOR UPDATE",(run_id,pid)).fetchone()
                    if not active: raise IngestionError("lease_expired")
                c.execute("SET LOCAL statement_timeout='5s'")
                grant=permission(c,pid)
                require_actor(c,pid,actor,"collect")
                current=c.execute("SELECT * FROM lavlah.https_sources WHERE permission_id=%s AND enabled",(pid,)).fetchone()
                if not current or current["endpoint"]!=endpoint or grant["source_url"]!=endpoint:
                    raise IngestionError("endpoint_not_authorized")
                now=c.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
                records,updated,digest=decode_envelope(raw,now,grant["freshness_days"])
                prior=c.execute("SELECT max(source_updated_at) AS t FROM lavlah.https_observations WHERE permission_id=%s",(pid,)).fetchone()["t"]
                if prior is not None and updated<=prior:
                    raise IngestionError("stale_replay")
                obs=c.execute("""INSERT INTO lavlah.https_observations(permission_id,source_updated_at,body_sha256,record_count,scheduler_run_id)
                    VALUES (%s,%s,%s,%s,%s) RETURNING id""",(pid,updated,digest,len(records),run_id)).fetchone()["id"]
                for record in records:
                    row,fingerprint=prepare(record)
                    c.execute("""INSERT INTO lavlah.ingestion_candidates(permission_id,submitted_by,name,category_slug,description,digest,observed_at,observation_day,https_observation_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,(timezone('UTC',%s::timestamptz)::date),%s)
                        ON CONFLICT(permission_id,digest,observation_day) DO NOTHING""",
                        (pid,actor,row["name"],row["category_slug"],row["description"],fingerprint,updated,updated,obs))
                c.execute("INSERT INTO lavlah.https_attempts(permission_id,outcome) VALUES (%s,'success')",(pid,))
                return {"observation_id":obs,"record_count":len(records)}
        except Exception as exc:
            with c.transaction():
                c.execute("SET LOCAL ROLE lavlah_ingestion")
                c.execute("INSERT INTO lavlah.https_attempts(permission_id,outcome) VALUES (%s,'failed')",(pid,))
            raise IngestionError("timeout" if isinstance(exc,IngestionError) and str(exc)=="timeout" else "collection_failed") from None
