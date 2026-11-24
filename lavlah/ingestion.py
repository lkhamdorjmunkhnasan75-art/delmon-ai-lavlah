"""Internal ingestion of pre-authorized structured records, no network crawling."""
import hashlib
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
    row=c.execute("""SELECT * FROM lavlah.ingestion_permissions
        WHERE id=%s AND NOT revoked AND valid_until>now()""",(identifier,)).fetchone()
    if not row:
        raise IngestionError("Active source permission required")
    url=urlsplit(row["source_url"])
    if url.scheme!="https" or not url.hostname or url.username or url.password or url.fragment:
        raise IngestionError("Invalid authorized public source URL")
    return row

class Ingestion:
    def __init__(self,dsn,review_dsn=None):
        self.dsn=dsn
        self.review_dsn=review_dsn

    def submit(self,permission_id,actor,records):
        permission_id,actor=UUID(str(permission_id)),UUID(str(actor))
        if not isinstance(records,list) or not 1<=len(records)<=100:
            raise IngestionError("Batch must contain 1–100 records")
        prepared=[prepare(row) for row in records]
        with closing(psycopg.connect(self.dsn,row_factory=dict_row)) as c:
            with c.transaction():
                c.execute("SET LOCAL ROLE lavlah_ingestion")
                c.execute("SET LOCAL statement_timeout='5s'")
                permission(c,permission_id)
                results=[]
                for row,digest in prepared:
                    inserted=c.execute("""INSERT INTO lavlah.ingestion_candidates
                        (permission_id,submitted_by,name,category_slug,description,digest)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(permission_id,digest) DO NOTHING RETURNING id""",
                        (permission_id,actor,row["name"],row["category_slug"],row["description"],digest)).fetchone()
                    results.append({"id":str(inserted["id"]) if inserted else None,"duplicate":inserted is None})
                return results

    def review(self,candidate_id,reviewer,*,approve,evidence):
        if not self.review_dsn or type(approve) is not bool:
            raise IngestionError("Reviewer connection and explicit decision required")
        candidate_id,reviewer=UUID(str(candidate_id)),UUID(str(reviewer))
        evidence=normalize(evidence,2000)
        if not evidence: raise IngestionError("Review evidence required")
        with closing(psycopg.connect(self.review_dsn,row_factory=dict_row)) as c:
            with c.transaction():
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("SET LOCAL statement_timeout='5s'")
                row=c.execute("SELECT * FROM lavlah.ingestion_candidates WHERE id=%s",(candidate_id,)).fetchone()
                if not row or row["submitted_by"]==reviewer:
                    raise IngestionError("Independent reviewer required")
                grant=permission(c,row["permission_id"])
                if c.execute("SELECT 1 FROM lavlah.ingestion_reviews WHERE candidate_id=%s",(candidate_id,)).fetchone():
                    raise IngestionError("Already reviewed")
                source=None
                if approve:
                    # Freshness starts at observation, not delayed approval.
                    source=c.execute("""INSERT INTO lavlah.sources
                        (organization_id,submitted_by,source_url,authorization_reference,observed_at,verified_by,verified_at,expires_at)
                        SELECT %s,%s,%s,%s,%s,%s,now(),LEAST(%s,%s+%s*interval '1 day')
                        WHERE LEAST(%s,%s+%s*interval '1 day')>now() RETURNING id""",
                        (grant["organization_id"],row["submitted_by"],grant["source_url"],grant["evidence"],row["observed_at"],reviewer,
                         grant["valid_until"],row["observed_at"],grant["freshness_days"],grant["valid_until"],row["observed_at"],grant["freshness_days"])).fetchone()
                    if not source: raise IngestionError("Candidate expired; collect fresh evidence")
                    source=source["id"]
                    c.execute("""INSERT INTO lavlah.public_listings
                        (organization_id,source_id,name,category_slug,description,public_source_url)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(organization_id) DO UPDATE SET source_id=excluded.source_id,name=excluded.name,
                        category_slug=excluded.category_slug,description=excluded.description,
                        public_source_url=excluded.public_source_url,approved_at=now()""",
                        (grant["organization_id"],source,row["name"],row["category_slug"],row["description"],grant["source_url"]))
                c.execute("""INSERT INTO lavlah.ingestion_reviews(candidate_id,reviewer_id,decision,evidence,source_id)
                    VALUES (%s,%s,%s,%s,%s)""",(candidate_id,reviewer,"approved" if approve else "rejected",evidence,source))
                return {"decision":"approved" if approve else "rejected","source_id":str(source) if source else None}
