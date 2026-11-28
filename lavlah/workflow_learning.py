"""Offline synthetic pilot only; no production ingestion or publication."""
from dataclasses import dataclass
import hashlib
import unicodedata

CATEGORIES = frozenset(("location", "product", "hours", "price", "delivery", "other"))

@dataclass(frozen=True)
class Example:
    organization: str
    category: str
    question: str
    answer: str
    fingerprint: str
    state: str = "pending"

def normalize(value: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("invalid field")
    value = " ".join(unicodedata.normalize("NFC", value).split())
    if not value or len(value) > limit:
        raise ValueError("invalid field")
    return value

class SyntheticPilot:
    """In-memory fixtures, never a trusted public search source."""
    def __init__(self):
        self._records = {}

    def add(self, organization: str, category: str, question: str, answer: str, *, synthetic: bool = False) -> Example:
        if synthetic is not True:
            raise ValueError("synthetic fixtures only")
        organization = normalize(organization, 128)
        if category not in CATEGORIES:
            raise ValueError("invalid category")
        question = normalize(question, 1000)
        answer = normalize(answer, 2000)
        digest = hashlib.sha256(question.casefold().encode("utf-8")).hexdigest()
        key = (organization, digest)
        if key in self._records:
            raise ValueError("duplicate question")
        record = Example(organization, category, question, answer, digest)
        self._records[key] = record
        return record
