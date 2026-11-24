import unittest

from lavlah.inquiry import Inquiry, InquiryStatus


class InquiryTests(unittest.TestCase):
    def setUp(self):
        self.inquiry = Inquiry.start("request-1", "case-1", "person-1")

    def test_success_charges_only_after_resolution(self):
        self.assertEqual(self.inquiry.quoted_mnt, 1_000)
        self.assertIs(type(self.inquiry.quoted_mnt), int)
        self.assertEqual(self.inquiry.charged_mnt, 0)
        with self.assertRaises(ValueError):
            self.inquiry.finish(resolved=True)

        authorized = self.inquiry.authorize(1_000)
        self.assertEqual(authorized.status, InquiryStatus.AUTHORIZED)
        self.assertEqual(authorized.charged_mnt, 0)
        resolved = authorized.finish(resolved=True)
        self.assertEqual(resolved.status, InquiryStatus.RESOLVED)
        self.assertEqual((resolved.charged_mnt, resolved.refunded_mnt), (1_000, 0))

    def test_consent_must_match_integer_quote(self):
        for amount in (0, 999, 1_001, 1000.0, "1000", True):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.inquiry.authorize(amount)

    def test_failed_authorized_inquiry_refunds_full_amount(self):
        failed = self.inquiry.authorize(1_000).finish(resolved=False)
        self.assertEqual(failed.status, InquiryStatus.FAILED)
        self.assertEqual((failed.charged_mnt, failed.refunded_mnt), (0, 1_000))

    def test_failed_inquiry_without_authorization_has_nothing_to_refund(self):
        failed = self.inquiry.finish(resolved=False)
        self.assertEqual((failed.charged_mnt, failed.refunded_mnt), (0, 0))
        with self.assertRaises(ValueError):
            failed.authorize(1_000)

    def test_emergency_inquiry_is_free(self):
        emergency = Inquiry.start("emergency-1", "case-1", "person-1", emergency=True)
        self.assertEqual(emergency.quoted_mnt, 0)
        with self.assertRaises(ValueError):
            emergency.authorize(1_000)
        for resolved in (True, False):
            with self.subTest(resolved=resolved):
                finished = emergency.finish(resolved=resolved)
                self.assertEqual((finished.charged_mnt, finished.refunded_mnt), (0, 0))

    def test_same_case_clarification_is_free(self):
        prior = self.inquiry.authorize(1_000).finish(resolved=True)
        follow_up = Inquiry.start(
            "request-2", "case-1", "person-1", clarification_of=prior
        )
        self.assertEqual(follow_up.quoted_mnt, 0)
        self.assertEqual(follow_up.finish(resolved=True).charged_mnt, 0)

    def test_clarification_requires_matching_case_and_requester_and_resolved_prior(self):
        prior = self.inquiry.authorize(1_000).finish(resolved=True)
        for request, case, person, original in (
            ("request-2", "case-2", "person-1", prior),
            ("request-2", "case-1", "person-2", prior),
            ("request-2", "case-1", "person-1", self.inquiry),
            ("request-1", "case-1", "person-1", prior),
        ):
            with self.subTest(request=request, case=case, person=person, prior=original):
                with self.assertRaises(ValueError):
                    Inquiry.start(request, case, person, clarification_of=original)

    def test_retries_preserve_outcome_and_amounts(self):
        authorized = self.inquiry.authorize(1_000)
        self.assertIs(authorized.authorize(1_000), authorized)
        for resolved in (True, False):
            with self.subTest(resolved=resolved):
                completed = authorized.finish(resolved=resolved)
                self.assertIs(completed.finish(resolved=resolved), completed)
                self.assertIs(completed.authorize(1_000), completed)
                with self.assertRaises(ValueError):
                    completed.finish(resolved=not resolved)
