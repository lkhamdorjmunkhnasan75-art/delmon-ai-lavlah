"""Synthetic pilot rate control; no raw identity or request content persisted."""
import hashlib
import math
from contextlib import closing
import psycopg
from psycopg.rows import dict_row
from lavlah.identity_store import checked_dsn,check_connection

class Limited(Exception):
    def __init__(self,retry):
        self.retry=retry

def principal_bucket(subject):
    return "principal:"+hashlib.sha256(subject.encode()).hexdigest()

def reserve(budgets):
    """All budgets commit together or none; global bucket serializes admission."""
    dsn=checked_dsn("LAVLAH_RATE_DSN","lavlah_rate_login")
    with closing(psycopg.connect(dsn,hostaddr="127.0.0.1",connect_timeout=3,row_factory=dict_row)) as c:
        with c.transaction():
            c.execute("SET LOCAL statement_timeout='2s'")
            c.execute("SET LOCAL lock_timeout='1s'")
            check_connection(c,"lavlah_rate_login")
            c.execute("SET LOCAL ROLE lavlah_rate")
            c.execute("SELECT pg_advisory_xact_lock(910003)")
            now=c.execute("SELECT extract(epoch FROM clock_timestamp()) AS t").fetchone()["t"]
            window=int(now)//60*60
            retry=max(1,math.ceil(window+60-now))
            c.execute("DELETE FROM lavlah.api_budgets WHERE window_start<%s",(window,))
            for key,limit in sorted(budgets.items()):
                if not 1<=limit<=10000 or len(key)>100:raise ValueError("Invalid budget")
                result=c.execute("""INSERT INTO lavlah.api_budgets(bucket,window_start,hits)
                    VALUES (%s,%s,1) ON CONFLICT(bucket) DO UPDATE
                    SET hits=lavlah.api_budgets.hits+1
                    WHERE lavlah.api_budgets.hits<%s RETURNING hits""",(key,window,limit)).fetchone()
                if not result:raise Limited(retry)
            return retry
