"""Offline evaluation only. Not an authorization or publication service."""
from dataclasses import dataclass
from datetime import datetime, timezone
from lavlah.workflow_learning import Example, normalize

@dataclass(frozen=True)
class Review:
    example: Example
    reviewer: str
    source_reference: str
    expires_at: datetime
    approved: bool
    revoked: bool = False

def eligible_for_evaluation(review: Review, organization: str, now: datetime) -> bool:
    if not isinstance(review, Review) or not isinstance(review.example, Example):
        return False
    try:
        if now.utcoffset() is None or review.expires_at.utcoffset() is None:
            return False
        normalize(review.reviewer, 128)
        normalize(review.source_reference, 500)
        return (
            review.example.organization == organization
            and review.example.state == "pending"
            and review.approved is True
            and review.revoked is False
            and now < review.expires_at
        )
    except (ValueError, TypeError, AttributeError):
        return False
