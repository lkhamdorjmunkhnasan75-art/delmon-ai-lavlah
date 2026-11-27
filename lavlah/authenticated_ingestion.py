"""Internal synthetic-token entrypoint. Never accepts an actor UUID from callers."""
import os
from lavlah.identity_store import identity_transaction, checked_dsn
from lavlah.ingestion import Ingestion, IngestionError

class AuthenticatedIngestion:
    def __init__(self,*,review_login="lavlah_review_test"):
        if os.getenv("LAVLAH_INGESTION_STRICT")!="1":
            raise IngestionError("Strict ingestion required")
        self.service=Ingestion(checked_dsn("LAVLAH_INGESTION_DSN","lavlah_ingest_test"),
                               checked_dsn("LAVLAH_REVIEW_DSN",review_login),
                               review_login=review_login)
    def submit(self,token,permission_id,records):
        with identity_transaction(token) as c:
            actor=c.execute("SELECT id FROM lavlah.users").fetchone()["id"]
            return self.service.submit(permission_id,actor,records)
    def review(self,token,candidate_id,*,approve,evidence):
        with identity_transaction(token) as c:
            actor=c.execute("SELECT id FROM lavlah.users").fetchone()["id"]
            return self.service.review(candidate_id,actor,approve=approve,evidence=evidence)
