import unittest
from datetime import date

from lavlah.subscription import (
    ANNUAL_ORGANIZATION_PRICE_MNT,
    SubscriptionTerm,
    organization_entitlements,
)


class SubscriptionTests(unittest.TestCase):
    def test_annual_price_and_free_listing(self):
        self.assertEqual(ANNUAL_ORGANIZATION_PRICE_MNT, 300_000)
        self.assertEqual(organization_entitlements(date(2026, 11, 24)), {"basic_listing"})

    def test_paid_entitlements_start_inclusively_and_expire_exclusively(self):
        term = SubscriptionTerm(date(2026, 11, 24), date(2027, 11, 24))
        paid = {"basic_listing", "catalog_management", "lead_rfq_intake", "analytics"}
        for on, expected in (
            (date(2026, 11, 23), {"basic_listing"}),
            (date(2026, 11, 24), paid),
            (date(2027, 11, 23), paid),
            (date(2027, 11, 24), {"basic_listing"}),
        ):
            with self.subTest(on=on):
                self.assertEqual(organization_entitlements(on, term), expected)

    def test_invalid_term_is_rejected(self):
        with self.assertRaises(ValueError):
            SubscriptionTerm(date(2027, 11, 24), date(2026, 11, 24))
