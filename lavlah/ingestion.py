"""Internal ingestion of pre-authorized structured records, no network crawling."""
import hashlib
import os
import json
import unicodedata
from contextlib import closing
from urllib.parse import urlsplit
from uuid import UUID
import psycopg
from psycopg.rows import dict_row

class IngestionError(ValueError):
    pass

def normalize(value, maximum):
    if not isinstance(value,str):
        raise IngestionError("Text required")
    value=" ".join(unicodedata.normalize("NFKC",value).split())
    if len(value)>maximum or any(unicodedata.category(ch).startswith("C") for ch in value):
        raise IngestionError("Invalid text")
    return value

def prepare(record):
    if set(record)!={"name","category_slug","description"}:
        raise IngestionError("Only approved public fields allowed")
    name=normalize(record["name"],300)
    category=normalize(record["category_slug"],80)
    description=normalize(record["description"],4000)
    if not name or not category:
        raise IngestionError("Name and category required")
    payload={"name":name,"category_slug":category,"description":description}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return payload,digest

def permission(c,identifier):
    # Serialize permission changes and all ingestions/reviews for a permission.
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,7))",(str(identifier),))
    if os.getenv("LAVLAH_INGESTION_STRICT")=="1":
        if not c.execute("SELECT lavlah.lock_active_permission(%s) AS allowed",(identifier,)).fetchone()["allowed"]:
            raise IngestionError("Active source permission required")
    row=c.execute("""SELECT * FROM lavlah.ingestion_permissions
        WHERE id=%s AND NOT revoked AND valid_until>clock_timestamp()""",(identifier,)).fetchone()
    if not row:
        raise IngestionError("Active source permission required")
    url=urlsplit(row["source_url"])
    if url.scheme!="https" or not url.hostname or url.username or url.password or url.fragment:
        raise IngestionError("Invalid authorized public source URL")
    return row

def strict_connection(c,login):
    if os.getenv("LAVLAH_INGESTION_STRICT")=="1":
        from lavlah.identity_store import check_connection
        check_connection(c,login)

def require_actor(c,permission_id,actor,capability):
    if os.getenv("LAVLAH_INGESTION_STRICT")!="1":
        if os.getenv("LAVLAH_ENV") in ("pilot","production"):
            raise IngestionError("Strict ingestion required")
        return
    if os.getenv("LAVLAH_ENV")!="pilot" or os.getenv("LAVLAH_PILOT_ONLY")!="1":
        raise IngestionError("Strict pilot required")
    if not c.execute("SELECT lavlah.lock_actor_grant(%s,%s,%s) AS allowed",(permission_id,actor,capability)).fetchone()["allowed"]:
        raise IngestionError("Actor not authorized")

class Ingestion:
    def __init__(self,dsn,review_dsn=None,*,review_login="lavlah_review_test"):
        self.dsn=dsn
        self.review_dsn=review_dsn
        self.review_login=review_login

    def submit(self,permission_id,actor,records):
        permission_id,actor=UUID(str(permission_id)),UUID(str(actor))
        if not isinstance(records,list) or not 1<=len(records)<=100:
            raise IngestionError("Batch must contain 1–100 records")
        prepared=[prepare(row) for row in records]
        with closing(psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=5)) as c:
            with c.transaction():
                strict_connection(c,"lavlah_ingest_test")
                c.execute("SET LOCAL ROLE lavlah_ingestion")
                c.execute("SET LOCAL statement_timeout='5s'")
                permission(c,permission_id)
                require_actor(c,permission_id,actor,'collect')
                results=[]
                for row,digest in prepared:
                    inserted=c.execute("""INSERT INTO lavlah.ingestion_candidates
                        (permission_id,submitted_by,name,category_slug,description,digest)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(permission_id,digest,observation_day) DO NOTHING RETURNING id""",
                        (permission_id,actor,row["name"],row["category_slug"],row["description"],digest)).fetchone()
                    results.append({"id":str(inserted["id"]) if inserted else None,"duplicate":inserted is None})
                if os.getenv("LAVLAH_INGESTION_STRICT")=="1":
                    permission(c,permission_id)
                return results

    def review(self,candidate_id,reviewer,*,approve,evidence):
        if not self.review_dsn or type(approve) is not bool:
            raise IngestionError("Reviewer connection and explicit decision required")
        candidate_id,reviewer=UUID(str(candidate_id)),UUID(str(reviewer))
        evidence=normalize(evidence,2000)
        if not evidence: raise IngestionError("Review evidence required")
        with closing(psycopg.connect(self.review_dsn,row_factory=dict_row,connect_timeout=5)) as c:
            with c.transaction():
                strict_connection(c,self.review_login)
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("SET LOCAL statement_timeout='5s'")
                row=c.execute("SELECT * FROM lavlah.ingestion_candidates WHERE id=%s",(candidate_id,)).fetchone()
                if not row or row["submitted_by"]==reviewer:
                    raise IngestionError("Independent reviewer required")
                grant=permission(c,row["permission_id"])
                require_actor(c,row["permission_id"],reviewer,"review")
                c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,12))",(str(grant["organization_id"]),))
                if c.execute("SELECT 1 FROM lavlah.ingestion_reviews WHERE candidate_id=%s",(candidate_id,)).fetchone():
                    raise IngestionError("Already reviewed")
                if os.getenv("LAVLAH_INGESTION_STRICT")=="1":
                    try:
                        source=c.execute("SELECT lavlah.atomic_review(%s,%s,%s,%s) AS source_id",
                                         (candidate_id,reviewer,approve,evidence)).fetchone()["source_id"]
                    except psycopg.errors.InsufficientPrivilege:
                        raise IngestionError("Atomic review denied") from None
                    permission(c,row["permission_id"])
                    return {"decision":"approved" if approve else "rejected","source_id":str(source) if source else None}
                source=None
                if approve:
                    previous=c.execute("SELECT s.observed_at FROM lavlah.public_listings p JOIN lavlah.sources s ON s.id=p.source_id WHERE p.organization_id=%s",(grant["organization_id"],)).fetchone()
                    if previous and previous["observed_at"]>=row["observed_at"]:
                        raise IngestionError("Older or equal observation cannot replace publication")
                    # Freshness starts at observation, not delayed approval.
                    source=c.execute("""INSERT INTO lavlah.sources
                        (organization_id,submitted_by,source_url,authorization_reference,observed_at,verified_by,verified_at,expires_at)
                        SELECT %s,%s,%s,%s,%s,%s,now(),LEAST(%s,%s+%s*interval '1 day')
                        WHERE LEAST(%s,%s+%s*interval '1 day')>now() RETURNING id""",
                        (grant["organization_id"],row["submitted_by"],grant["source_url"],grant["evidence"],row["observed_at"],reviewer,
                         grant["valid_until"],row["observed_at"],grant["freshness_days"],grant["valid_until"],row["observed_at"],grant["freshness_days"])).fetchone()
                    if not source: raise IngestionError("Candidate expired; collect fresh evidence")
                    source=source["id"]
                c.execute("""INSERT INTO lavlah.ingestion_reviews(candidate_id,reviewer_id,decision,evidence,source_id)
                    VALUES (%s,%s,%s,%s,%s)""",(candidate_id,reviewer,"approved" if approve else "rejected",evidence,source))
                if approve:
                    c.execute("""INSERT INTO lavlah.public_listings
                        (organization_id,source_id,name,category_slug,description,public_source_url)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(organization_id) DO UPDATE SET source_id=excluded.source_id,name=excluded.name,
                        category_slug=excluded.category_slug,description=excluded.description,
                        public_source_url=excluded.public_source_url,approved_at=now()""",
                        (grant["organization_id"],source,row["name"],row["category_slug"],row["description"],grant["source_url"]))
                if os.getenv("LAVLAH_INGESTION_STRICT")=="1":
                    c.execute("""INSERT INTO lavlah.publication_audit(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,source_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",(candidate_id,row["permission_id"],grant["organization_id"],reviewer,row["digest"],row["observed_at"],"approved" if approve else "rejected",source))
                if os.getenv("LAVLAH_INGESTION_STRICT")=="1":
                    permission(c,row["permission_id"])
                return {"decision":"approved" if approve else "rejected","source_id":str(source) if source else None}
