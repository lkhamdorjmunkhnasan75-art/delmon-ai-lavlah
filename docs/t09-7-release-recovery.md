# T09.7 — Release and recovery review
Baseline 28b4cd4, 140 verified distinct tests. Target 142 (76 unit/API, 54 DB, 12 browser); CI pending.
Decision: production NO-GO. Synthetic disposable CI only. No deployment, merge, live source, real AI or payment approved.
## Evidence and residual risk register
| ID | Current mitigation | Unclosed release gate |
|---|---|---|
| A01 | Signed synthetic identity, transaction RLS, revocation | Real OIDC, membership lifecycle, trusted service SQL and independent tenant penetration review |
| A02 | Actual pilot DB identity, loopback pin, production denial | Separate production infrastructure, credentials, mandatory mode, network isolation |
| A03 | Shared PostgreSQL fixed-window limits, body deadlines | Distributed in-flight admission, hard cancellation, integrated load and trusted reverse proxy |
| A04 | Signed mock callbacks, replay and reconciliation | Provider sandbox, independent statement reconciliation, operator approval, key rotation |
| A05 | Scoped collector/reviewer identity | Restrict direct DB writes, administrative grant races, independent review |
| A06 | Monotonic publication, provenance, safe file open | Authentic publisher timestamps, revocation races, tamper-evident chain |
| A07 | Mock transition and ledger amount constraints | Complete ledger invariants and independent financial audit |
| A08 | Selection-only mock, privacy filters, usage and count/cost limits | Real model evaluation, retention/deletion, request deduplication, broader Mongolian corpus and PII evaluation |
| A09 | Process-bounded transport, shared scheduler and SSRF checks | Local IO hard deadline, egress deny-by-default, independent network review |
| A10 | Identity memory session, feedback, revocation | Real device/accessibility tests, legacy path retirement, production session and consent design |
| A11 | Disposable populated logical backup/restore, hashes, sequence and policy metadata | Offsite encrypted backups, independent keys, PITR/WAL, role/global restore, actual timed disaster drill |
| A12 | Read-only CI token, no persisted checkout credentials, pip check/audit, npm lock/audit | Hash-locked Python dependencies, immutable action/image pins, SBOM, secret scanning and independent review |
All twelve remain open for production; this is a targeted review of prior documented findings, not exhaustive independent security testing.
## Recovery runbook
Only run tests/recovery_seed.sql against the disposable CI postgres database after migrations 001–014. Run tests/backup_restore.sh in same CI service. It restores into a newly created disposable database and compares sorted row hashes, sequence last values, table/view/sequence ACL metadata, RLS policies and selected private journal grants. It verifies nonempty audit fixtures. The source database remains intact; this is logical restore, not full cluster disaster recovery. No real user data. Archive checksum detects accidental corruption, not malicious replacement. No production backup credentials or data.
Before real deployment, operator must agree RPO/RTO (proposed RPO 24 hours, RTO 4 hours, not measured), establish encrypted offsite backups with separate key access, verify WAL/PITR and global role restoration on separate infrastructure, time a recovery drill, test alerting and document rollback decision. Stop writes before a consistent final snapshot; never overwrite the only backup. Fail closed on mismatch.
## Independent review checklist (all pending)
- [ ] Independent reviewer checks stacked PRs and every migration, auth/role and direct-write boundary.
- [ ] Verify real deployment topology, TLS, egress, secret rotation and tenant isolation.
- [ ] Approve dependency locks, action/image pins, SBOM, secret and vulnerability scans.
- [ ] Independently repeat backup/restore and timed failover with synthetic data.
- [ ] Validate physical Android/iOS accessibility, session lifecycle and privacy deletion.
- [ ] Verify numeric budgets, distributed load, abuse and real provider sandbox only after separate authorization.
- [ ] Approve evidence-only AI quality, source licensing, financial reconciliation and consent.
- [ ] Obtain explicit human GO and separate integration approvals before any production deployment.
