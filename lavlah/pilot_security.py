"""Synthetic pilot only; no production identity provider or persistent credentials."""
import os
import secrets
import hmac
import hashlib
import time
import threading
import logging
from psycopg.conninfo import conninfo_to_dict

log=logging.getLogger("lavlah.pilot_security")
def event(code):
    log.info("pilot_security %s",code)

def enabled():
    if os.getenv("LAVLAH_ENV")!="pilot" or os.getenv("LAVLAH_PILOT_ONLY")!="1":
        return False
    try:
        d=conninfo_to_dict(os.environ["LAVLAH_PUBLIC_DSN"])
        return (d.get("host")=="127.0.0.1" and d.get("dbname")=="lavlah_pilot_test"
                and d.get("user")=="lavlah_integration_login"
                and set(d)<= {"host","port","dbname","user","password","sslmode"}
                and not any(os.getenv(k) for k in ("PGHOSTADDR","PGSERVICE","PGSERVICEFILE","PGOPTIONS")))
    except Exception:
        return False

class Security:
    def __init__(self,clock=time.monotonic):
        self.clock=clock
        self.lock=threading.Lock()
        self.sessions={}
        self.attempts={}
    def allow(self,key,limit,window=60):
        now=self.clock()
        with self.lock:
            self.attempts={k:v for k,v in self.attempts.items() if now<v[0]}
            if key not in self.attempts and len(self.attempts)>=1024:
                return False
            end,count=self.attempts.get(key,(now+window,0))
            if count>=limit:return False
            self.attempts[key]=(end,count+1)
            return True
    def login(self,password):
        expected=os.getenv("LAVLAH_PILOT_PASSWORD","")
        if len(expected)<24 or not hmac.compare_digest(password.encode(),expected.encode()):
            event("login_denied")
            return None
        token=secrets.token_urlsafe(32)
        now=self.clock()
        with self.lock:
            self.sessions={k:v for k,v in self.sessions.items() if v>now}
            if len(self.sessions)>=128:return None
            self.sessions[self.digest(token)]=now+900
        event("login_ok")
        return token
    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()
    def authorize(self,token):
        if not isinstance(token,str) or not 1<=len(token)<=128:return None
        key=self.digest(token)
        with self.lock:
            expiry=self.sessions.get(key,0)
            if expiry<=self.clock():
                self.sessions.pop(key,None)
                return None
            return key
    def logout(self,token):
        key=self.authorize(token)
        if key:
            with self.lock:self.sessions.pop(key,None)
            event("logout")
security=Security()
