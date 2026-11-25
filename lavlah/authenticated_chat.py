"""Synthetic pilot chat; no external model, source fetch or payment."""
import os
import re
import unicodedata
from uuid import UUID,uuid4
from urllib.parse import urlsplit
from lavlah.identity_store import identity_transaction
from lavlah.grounded_ai import respond

DAILY_BUDGET=200000
DAILY_COUNT=40
MAX_RESERVATION=70000

class ChatLimit(Exception):pass
class ChatPrivacy(ValueError):pass

def unsafe(text):
    if not isinstance(text,str):return True
    text=unicodedata.normalize("NFKC",text).casefold()
    return bool(re.search(r"\d{6,}|[\w.+-]+@[\w.-]+|(?:\d[\s().+-]*){8,}|ignore\s+(?:all|previous|prior)|system\s+prompt|нууц\s+үг|зааврыг\s+үл\s+тоомсор|<[^>]*>",text) or any(unicodedata.category(ch).startswith("C") for ch in text))

def safe_search(search):
    def run(q,category,limit,offset):
        result=[]
        for row in search(q,category,limit,offset):
            try:
                u=urlsplit(row["source_url"])
                if (u.scheme!="https" or not u.hostname or not u.hostname.endswith(".test") or u.username or u.password or u.query or u.fragment or u.port not in (None,443) or unsafe(row["name"]) or unsafe(row["description"]) or len(row["name"])>300 or len(row["description"])>4000):continue
                # Only synthetic fixture source paths, no arbitrary URL path data.
                if not re.fullmatch(r"/[a-zA-Z0-9/_-]{0,80}",u.path):continue
                result.append(row)
            except (ValueError,TypeError,KeyError,AttributeError):continue
        return result
    return run

def enabled():
    return all(os.getenv(k)=="1" for k in ("LAVLAH_ENABLE_IDENTITY_CHAT","LAVLAH_ENABLE_MOCK_AI","LAVLAH_PILOT_ONLY")) and os.getenv("LAVLAH_ENV")=="pilot"

def ask(token,question,search):
    if not enabled():raise ValueError("Chat disabled")
    with identity_transaction(token) as c:
        actor=c.execute("SELECT id FROM lavlah.users").fetchone()["id"]
        if unsafe(question):raise ChatPrivacy("Do not submit personal or instruction-like data")
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,14))",(str(actor),))
        totals=c.execute("""SELECT count(*) AS n,coalesce(sum(estimated_micro_mnt),0) AS cost FROM lavlah.chat_usage
            WHERE user_id=%s AND created_at>=date_trunc('day',clock_timestamp(),'UTC')""",(actor,)).fetchone()
        if totals["n"]>=DAILY_COUNT or totals["cost"]+MAX_RESERVATION>DAILY_BUDGET:raise ChatLimit()
        result=respond(question,safe_search(search))
        cost=result["usage"]["estimated_micro_mnt"]
        if cost is None:cost=MAX_RESERVATION
        if not 0<=cost<=MAX_RESERVATION:raise ValueError("Invalid cost")
        uid=uuid4()
        c.execute("INSERT INTO lavlah.chat_usage(id,user_id,outcome,estimated_micro_mnt) VALUES (%s,%s,%s,%s)",(uid,actor,result["status"],cost))
        result["usage_id"]=str(uid)
        return result

def feedback(token,usage_id,rating):
    if not enabled() or type(rating) is not int or rating not in (-1,1):raise ValueError("Invalid feedback")
    with identity_transaction(token) as c:
        actor=c.execute("SELECT id FROM lavlah.users").fetchone()["id"]
        uid=UUID(str(usage_id))
        if not c.execute("SELECT 1 FROM lavlah.chat_usage WHERE id=%s AND user_id=%s",(uid,actor)).fetchone():raise ValueError("Unknown answer")
        c.execute("INSERT INTO lavlah.chat_feedback VALUES (%s,%s,%s) ON CONFLICT(usage_id) DO UPDATE SET rating=excluded.rating",(uid,actor,rating))
        return {"saved":True}
