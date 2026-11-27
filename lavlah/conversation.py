"""Text-only conversation boundary; adapter must enforce public visibility."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

@dataclass(frozen=True)
class PublicRecord:
    name: str
    description: str
    source_url: str
    verified_at: datetime
    expires_at: datetime
    published: bool

class PublicSearch(Protocol):
    def search(self, query: str, limit: int) -> tuple[PublicRecord, ...]: ...

@dataclass(frozen=True)
class Reply:
    status: str
    message: str
    records: tuple[PublicRecord, ...] = ()

def respond(query: str, adapter: PublicSearch) -> Reply:
    if not isinstance(query, str) or len(query) > 1000:
        return Reply("clarification", "Асуултаа товч бичнэ үү.")
    query = " ".join(query.split())
    if not query:
        return Reply("clarification", "Та юу хайж байна вэ?")
    try:
        records = adapter.search(query, 5)
        if not isinstance(records, tuple) or len(records) > 5:
            raise ValueError("invalid adapter response")
        now = datetime.now(timezone.utc)
        approved = []
        for record in records:
            if not isinstance(record, PublicRecord):
                raise ValueError("invalid record")
            if record.published is not True or not (record.verified_at <= now < record.expires_at):
                continue
            if not all(isinstance(v, str) for v in (record.name, record.description, record.source_url)):
                raise ValueError("invalid public fields")
            url = urlsplit(record.source_url)
            if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
                raise ValueError("invalid source")
            approved.append(record)
        if approved:
            return Reply("answer", "Баталгаатай мэдээлэл олдлоо.", tuple(approved))
        return Reply("unavailable", "Баталгаатай мэдээлэл олдсонгүй.")
    except Exception:
        return Reply("unavailable", "Мэдээллийг одоогоор шалгах боломжгүй байна.")
