"""Pure pricing and lifecycle for a personal inquiry."""

from dataclasses import dataclass, replace
from enum import Enum

PERSONAL_INQUIRY_PRICE_MNT = 1_000


class InquiryKind(Enum):
    PERSONAL = "personal"
    EMERGENCY = "emergency"
    CLARIFICATION = "clarification"


class InquiryStatus(Enum):
    OPEN = "open"
    AUTHORIZED = "authorized"
    RESOLVED = "resolved"
    FAILED = "failed"


@dataclass(frozen=True)
class Inquiry:
    request_id: str
    case_id: str
    requester_id: str
    kind: InquiryKind
    status: InquiryStatus = InquiryStatus.OPEN
    authorized_mnt: int = 0

    @classmethod
    def start(
        cls,
        request_id: str,
        case_id: str,
        requester_id: str,
        *,
        emergency: bool = False,
        clarification_of: "Inquiry | None" = None,
    ) -> "Inquiry":
        if not all(identifier.strip() for identifier in (request_id, case_id, requester_id)):
            raise ValueError("Request, case and requester IDs are required")

        kind = InquiryKind.EMERGENCY if emergency else InquiryKind.PERSONAL
        if clarification_of is not None:
            if (
                clarification_of.status is not InquiryStatus.RESOLVED
                or clarification_of.case_id != case_id
                or clarification_of.requester_id != requester_id
                or clarification_of.request_id == request_id
            ):
                raise ValueError("Clarification requires a prior resolved request in the same case")
            kind = InquiryKind.CLARIFICATION
        return cls(request_id, case_id, requester_id, kind)

    @property
    def quoted_mnt(self) -> int:
        return PERSONAL_INQUIRY_PRICE_MNT if self.kind is InquiryKind.PERSONAL else 0

    @property
    def charged_mnt(self) -> int:
        return self.authorized_mnt if self.status is InquiryStatus.RESOLVED else 0

    @property
    def refunded_mnt(self) -> int:
        """Amount to return or release if this request fails after authorization."""
        return self.authorized_mnt if self.status is InquiryStatus.FAILED else 0

    def authorize(self, consented_mnt: int) -> "Inquiry":
        if (
            not self.quoted_mnt
            or type(consented_mnt) is not int
            or consented_mnt != self.quoted_mnt
        ):
            raise ValueError("Consent must match the paid inquiry quote in integer MNT")
        if self.authorized_mnt == consented_mnt:
            return self
        if self.status is not InquiryStatus.OPEN:
            raise ValueError("Only open inquiries can be authorized")
        return replace(self, status=InquiryStatus.AUTHORIZED, authorized_mnt=consented_mnt)

    def finish(self, *, resolved: bool) -> "Inquiry":
        outcome = InquiryStatus.RESOLVED if resolved else InquiryStatus.FAILED
        if self.status is outcome:
            return self
        if self.status in (InquiryStatus.RESOLVED, InquiryStatus.FAILED):
            raise ValueError("A completed inquiry cannot change outcome")
        if resolved and self.quoted_mnt and self.status is not InquiryStatus.AUTHORIZED:
            raise ValueError("Resolving a paid inquiry requires consent to its quote")
        return replace(self, status=outcome)
