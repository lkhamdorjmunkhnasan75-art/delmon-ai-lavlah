"""Organization active-service entitlement for a recorded subscription term."""

from dataclasses import dataclass
from datetime import date

ANNUAL_ORGANIZATION_PRICE_MNT = 300_000
BASIC_LISTING = "basic_listing"
PAID_FEATURES = frozenset({"catalog_management", "lead_rfq_intake", "analytics"})


@dataclass(frozen=True)
class SubscriptionTerm:
    starts_on: date
    expires_on: date

    def __post_init__(self) -> None:
        if self.expires_on <= self.starts_on:
            raise ValueError("Expiry must follow the start date")


def organization_entitlements(
    on: date, term: SubscriptionTerm | None = None
) -> frozenset[str]:
    entitlements = frozenset({BASIC_LISTING})
    if term is not None and term.starts_on <= on < term.expires_on:
        return entitlements | PAID_FEATURES
    return entitlements
