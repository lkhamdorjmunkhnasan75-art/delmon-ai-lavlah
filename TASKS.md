# MVP backlog
- [x] T01 Implement pure inquiry pricing and lifecycle with integer MNT; tests for successful, failed, emergency, clarification and repeated requests.
- [x] T02 Set up Python test CI and document local run.
- [x] T03 Design user and organization permissions, source records and migrations.
- [x] T04 Build directory search API and provenance. Verified: Python and PostgreSQL CI, including 5 real database integration tests on 4e8df033.
- [x] T05 Build mobile Mongolian UI (verified legacy Chromium tests).
- [x] T05.1 Next.js PWA and automated browser integration.
- [x] T05.2 PWA hardening, committed npm lockfile, reproducible npm ci, localized public category names and CSP browser tests. Verified on db1d1fa: 16 unit/API + 6 PostgreSQL + 3 legacy browser + 3 PWA browser tests passed; npm audit reported zero vulnerabilities; production build and lockfile diff guard passed. CI: 45423317869 / 45423317884.
- [ ] Release gates: physical Android/iOS install verification, production HTTPS/configuration, security review and review/merge of stacked draft PRs. Unknown untranslated category names retain a fallback label.
- [x] T06 Mock payment adapter, transactional ledger, idempotency, refund and annual entitlements. Verified on 97f3a77: 33 distinct tests passed; CI 45428849039 / 45428848941. Mock only; authenticated service wiring, provider sandbox and reconciliation remain release gates.
- [x] T07 Authorized structured ingestion and human review. Verified on 54c3fac: 37 distinct tests; CI 45433716426 / 45433716494 passed.
- [x] T07.1 Scheduled local adapter, refresh candidates, exact cross-source deduplication and operational tests. Verified on 032c1c7: 41 distinct tests; CI 45444574453 / 45444574267 passed. No live scheduler activated.
- [x] T07.2 Authorized HTTPS JSON adapter, endpoint registry, SSRF defense, per-permission rate limits and freshness evidence. Verified on 6cf48c8: 49 distinct tests; CI 45510618763 / 45510618749 passed, including mocked TLS and mid-fetch revocation. Offline transport only; production egress, aggregate rate limits, scheduler wiring, independent freshness verification and identity/security remain release gates.
- [ ] T08 Pilot and security review.
Start T01 and T02. Keep each change reviewable. Update task status only after verified tests. 

Organization subscription: 300000 MNT/year; free basic listing; paid service includes catalog management, lead/RFQ intake and analytics. Do not imply unlimited AI usage. Subscription entitlement and expiry must be tested; no live billing without approval.
