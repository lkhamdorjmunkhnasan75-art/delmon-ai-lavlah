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
            or (ip.version==6 and (ip.sixtofour or ip.teredo))):
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
