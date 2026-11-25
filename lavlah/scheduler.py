"""Opt-in integrated scheduler; network access is disabled unless explicitly enabled."""
import json
import os
from contextlib import closing
from functools import partial
import psycopg
from psycopg.rows import dict_row
from lavlah.collection import Runner, LocalJSONAdapter
from lavlah.https_adapter import collect_registered, endpoint_parts, fetch_json
from lavlah.bounded_transport import bounded_fetch
from lavlah.ingestion import IngestionError

DOMAIN_INTERVAL=60
LEASE_SECONDS=120

def reserve_domain(c,endpoint):
    host,_=endpoint_parts(endpoint)
    # A universal bucket prevents alias/subdomain bypass even with missing mappings.
    group=c.execute("SELECT group_key FROM lavlah.https_domain_groups WHERE host=%s",(host,)).fetchone()
    for key in sorted({"!global",host,"group:"+group["group_key"] if group else "!global"}):
        _reserve_slot(c,key)

def _reserve_slot(c,host):
    row=c.execute("""INSERT INTO lavlah.https_domain_slots(host,next_at)
        VALUES (%s,clock_timestamp()+%s*interval '1 second')
        ON CONFLICT(host) DO UPDATE SET next_at=excluded.next_at
        WHERE lavlah.https_domain_slots.next_at<=clock_timestamp()
        RETURNING host""",(host,DOMAIN_INTERVAL)).fetchone()
    if not row: raise IngestionError("rate_limited")

class Scheduler:
    def __init__(self,dsn,*,transport=None,allow_network=False):
        self.dsn=dsn
        self.transport=transport if transport is not None else partial(bounded_fetch,fetch=fetch_json)
        self.enabled=transport is not None or allow_network
    def _connect(self):
        return closing(psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=5))
    @staticmethod
    def _role(c):
        c.execute("SET LOCAL ROLE lavlah_ingestion")
        c.execute("SET LOCAL statement_timeout='5s'")
        c.execute("SET LOCAL lock_timeout='3s'")
    def recover(self):
        with self._connect() as c:
            with c.transaction():
                self._role(c)
                rows=c.execute("""SELECT r.id,r.permission_id FROM lavlah.https_scheduler_runs r
                    WHERE outcome='running' AND lease_until<=clock_timestamp()
                    ORDER BY id FOR UPDATE SKIP LOCKED""").fetchall()
                for row in rows:
                    obs=c.execute("SELECT record_count FROM lavlah.https_observations WHERE scheduler_run_id=%s",(row["id"],)).fetchone()
                    c.execute("""UPDATE lavlah.https_scheduler_runs SET outcome=%s,record_count=%s,
                        finished_at=clock_timestamp(),error_code=%s WHERE id=%s""",
                        ("success" if obs else "interrupted",obs["record_count"] if obs else 0,None if obs else "lease_expired",row["id"]))
                    c.execute("""UPDATE lavlah.collection_jobs SET
                        next_run=clock_timestamp()+(CASE WHEN %s THEN interval_minutes ELSE 15 END)*interval '1 minute',
                        failures=CASE WHEN %s THEN 0 ELSE least(failures+1,16) END WHERE permission_id=%s""",
                        (bool(obs),bool(obs),row["permission_id"]))
                return len(rows)
    def _claim(self):
        with self._connect() as c:
            with c.transaction():
                self._role(c)
                job=c.execute("""SELECT j.* FROM lavlah.collection_jobs j
                    JOIN lavlah.https_sources s ON s.permission_id=j.permission_id
                    WHERE j.enabled AND j.next_run<=clock_timestamp() AND s.enabled
                    AND s.next_fetch_at<=clock_timestamp()
                    AND NOT EXISTS (SELECT 1 FROM lavlah.https_scheduler_runs r
                        WHERE r.permission_id=j.permission_id AND r.outcome='running')
                    ORDER BY j.next_run,j.permission_id LIMIT 1 FOR UPDATE OF j SKIP LOCKED""").fetchone()
                if not job: return None
                run=c.execute("""INSERT INTO lavlah.https_scheduler_runs(permission_id,lease_until)
                    VALUES (%s,clock_timestamp()+%s*interval '1 second') RETURNING id""",
                    (job["permission_id"],LEASE_SECONDS)).fetchone()
                return job,run["id"]
    def _finish(self,job,run,outcome,count,code):
        with self._connect() as c:
            with c.transaction():
                self._role(c)
                row=c.execute("""UPDATE lavlah.https_scheduler_runs SET outcome=%s,record_count=%s,error_code=%s,
                    finished_at=clock_timestamp() WHERE id=%s AND outcome='running' RETURNING id""",
                    (outcome,count,code,run)).fetchone()
                if not row: return False
                failures=0 if outcome=="success" else min(job["failures"]+1,16)
                delay=job["interval_minutes"] if outcome in ("success","blocked") else min(job["interval_minutes"],15*2**min(failures-1,8))
                if outcome=="deferred":
                    failures=job["failures"]
                    delay=1
                c.execute("UPDATE lavlah.collection_jobs SET next_run=clock_timestamp()+%s*interval '1 minute',failures=%s WHERE permission_id=%s",(delay,failures,job["permission_id"]))
                return True
    def run_due(self,limit=10):
        if type(limit) is not int or not 1<=limit<=100: raise ValueError("Invalid limit")
        if not self.enabled: return []
        self.recover()
        results=[]
        for _ in range(limit):
            claimed=self._claim()
            if not claimed: break
            job,run=claimed
            outcome,code,count="success",None,0
            try:
                result=collect_registered(self.dsn,job["permission_id"],job["actor_id"],self.transport,
                    reserve_domain=reserve_domain,run_id=run)
                count=result["record_count"]
            except IngestionError as exc:
                code=str(exc)
                if code=="Active source permission required": code="permission_invalid"
                if code not in ("permission_invalid","rate_limited","endpoint_not_authorized","timeout"):
                    code="collection_failed"
                outcome="deferred" if code=="rate_limited" else "blocked" if code in ("permission_invalid","endpoint_not_authorized") else "failed"
            except psycopg.Error:
                outcome,code="failed","database_error"
            if self._finish(job,run,outcome,count,code):
                results.append({"run_id":str(run),"outcome":outcome,"record_count":count,"error_code":code})
        return results
    def alerts(self):
        with self._connect() as c:
            with c.transaction():
                self._role(c)
                return c.execute("SELECT * FROM lavlah.scheduler_alerts ORDER BY code").fetchall()
    def stats(self):
        with self._connect() as c:
            with c.transaction():
                self._role(c)
                return c.execute("SELECT * FROM lavlah.https_scheduler_stats ORDER BY outcome").fetchall()

def main():
    dsn=os.environ["LAVLAH_INGESTION_DSN"]
    scheduler=Scheduler(dsn,allow_network=os.environ.get("LAVLAH_ENABLE_HTTPS")=="1")
    local=Runner(dsn,LocalJSONAdapter(os.environ["LAVLAH_FEED_DIR"]),exclude_https=True)
    print(json.dumps({"local":local.run_due(),"https":scheduler.run_due(),"https_stats":scheduler.stats(),"alerts":scheduler.alerts()}))

if __name__=="__main__":
    main()
