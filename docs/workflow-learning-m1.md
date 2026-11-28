# Workflow Learning M1 — proposed pilot

Inspired by human demonstration data collection, not a Mecka integration or licensed dataset import.

Pilot: one consenting retail organization; collect synthetic or explicitly authorized, redacted text examples of recurring information requests. No ambient recording, customer audio, video, personal identifiers or production ingestion in M1.

Record schema: opaque example ID, organization scope, task category, sanitized question, approved answer, public source reference, consent/authorization reference, reviewer ID, review state, expiry, version. Keep authorization and reviewer metadata private. Default pending; only reviewed, unexpired public answers may enter the public search projection. Revocation removes eligibility. Separate evaluation examples from retrieval data; no automatic training or publication.

Acceptance: 100 authorized examples target (not yet collected), independent human review, duplicate detection, source freshness, cross-tenant isolation, refusal when no approved answer, audit and deletion tests. Measure grounded accuracy, unsupported answer rate, clarification rate and latency. Start with synthetic fixtures. Existing Lavlah reviewer and publication gates remain mandatory.

Next: verify public search adapter and database contract before implementing ingestion. No production data, external outreach or merge without approval.
