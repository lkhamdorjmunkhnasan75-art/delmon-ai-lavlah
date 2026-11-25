"""Opt-in scheduled collector. No automatic publication or untrusted URL fetching."""
import json
import os
import stat
from contextlib import closing
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from lavlah.ingestion import prepare, permission, IngestionError, require_actor, strict_connection

class LocalJSONAdapter:
    """Operator-provisioned file mapping by permission UUID; never accepts remote paths."""
    def __init__(self, root):
        self.root=Path(root).resolve()
    def collect(self, grant):
        path=self.root/(str(UUID(str(grant["id"])))+".json")
        try:
            root=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root)
                with os.fdopen(fd,"rb") as f:
                    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                        raise IngestionError("Invalid feed type")
                    raw=f.read(512001)
            finally:os.close(root)
        except OSError:raise IngestionError("Invalid feed path") from None
        if len(raw)>512000:
            raise IngestionError("Feed too large")
        records=json.loads(raw)
        if not isinstance(records,list) or not 1<=len(records)<=100:
            raise IngestionError("Invalid batch")
        return records

class Runner:
    def __init__(self,dsn,adapter,*,exclude_https=False):
        self.dsn,self.adapter=dsn,adapter
        self.exclude_https=exclude_https
    def run_due(self,limit=10):
        if type(limit) is not int or not 1<=limit<=100:
            raise ValueError("Invalid limit")
        results=[]
        for _ in range(limit):
            with closing(psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=5)) as c:
                with c.transaction():
                    strict_connection(c,"lavlah_ingest_test")
                    c.execute("SET LOCAL ROLE lavlah_ingestion")
                    c.execute("SET LOCAL statement_timeout='10s'")
                    query="""SELECT * FROM lavlah.collection_jobs
                      WHERE enabled AND next_run<=now()"""
                    if self.exclude_https:
                        query+=" AND NOT EXISTS (SELECT 1 FROM lavlah.https_sources s WHERE s.permission_id=collection_jobs.permission_id)"
                    job=c.execute(query+" ORDER BY next_run,permission_id LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
                    if not job: break
                    pid=job["permission_id"]
                    outcome,code,count="success",None,0
                    try:
                        with c.transaction():
                            grant=permission(c,pid)
                            require_actor(c,pid,job["actor_id"],"collect")
                            try: records=self.adapter.collect(grant)
                            except Exception: raise IngestionError("adapter_error") from None
                            permission(c,pid)
                            require_actor(c,pid,job["actor_id"],"collect")
                            if not isinstance(records,list) or not 1<=len(records)<=100:
                                raise IngestionError("record_invalid")
                            for record in records:
                                row,digest=prepare(record)
                                c.execute("""INSERT INTO lavlah.ingestion_candidates
                                  (permission_id,submitted_by,name,category_slug,description,digest)
                                  VALUES (%s,%s,%s,%s,%s,%s)
                                  ON CONFLICT(permission_id,digest,observation_day) DO NOTHING""",
                                  (pid,job["actor_id"],row["name"],row["category_slug"],row["description"],digest))
                            count=len(records)
                    except IngestionError as exc:
                        code="permission_invalid" if str(exc)=="Active source permission required" else "adapter_error" if str(exc)=="adapter_error" else "record_invalid"
                        outcome="blocked" if code=="permission_invalid" else "failed"
                    except psycopg.Error:
                        outcome,code="failed","database_error"
                    failures=0 if outcome=="success" else min(job["failures"]+1,16)
                    delay=job["interval_minutes"] if outcome in ("success","blocked") else min(job["interval_minutes"],15*2**min(failures-1,8))
                    c.execute("UPDATE lavlah.collection_jobs SET failures=%s,next_run=now()+%s*interval '1 minute' WHERE permission_id=%s",(failures,delay,pid))
                    c.execute("INSERT INTO lavlah.collection_runs(permission_id,outcome,record_count,error_code) VALUES (%s,%s,%s,%s)",(pid,outcome,count,code))
                    results.append({"permission_id":str(pid),"outcome":outcome,"record_count":count,"error_code":code})
        return results

if __name__=="__main__":
    import os
    print(json.dumps(Runner(os.environ["LAVLAH_INGESTION_DSN"],LocalJSONAdapter(os.environ["LAVLAH_FEED_DIR"])).run_due()))
