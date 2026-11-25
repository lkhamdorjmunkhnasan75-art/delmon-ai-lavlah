# T09.1 — Integrated architecture and security audit
Date: 2026-11-25. Scope: offline static review, not a penetration test or production approval.
Baseline: f4adf9cea5654a2f728493a4f507537898dfdf1c; executable CI baseline 9616a1bc2487dc190ebc3bd065f043025da3f4bd, Python run 45605354317 and PostgreSQL run 45605354315: 97 distinct tests (53 unit/API, 33 DB, 11 browser), backup/restore selected ACL and table data passed, npm audit zero reported. No new test execution claimed by this document. Main 2d4321a4b2351acdf1b6e8cf367ec5235b6089da; compare ahead 180, behind 0. All 16 PRs draft/unmerged, sequential bases. No merge/deploy/source/model/payment access.
## Coverage
PR metadata #1–16 and cumulative compare inspected. Selected code at pinned head reviewed: directory, ingestion and billing migrations 001/004/005/009; public_api, pilot_security, inquiry, subscription, mock_billing, ingestion, collection, https_adapter, scheduler, bounded_transport, pilot_fixtures, grounded_ai; Next pilot proxy/chat and public proxy; requirements, Python CI and restore script. Prior CI and task documentation used for other modules; not exhaustive line-by-line review of every file, migration or PR diff.
| PR | Scope | Head | Main issue IDs |
|---|---|---|---|
| 1 | foundation/RLS/pricing | 937a308 | A01 A07 |
| 2 | public directory | 4e26ba9 | A03 A08 |
| 3 | legacy mobile UI | 9244ec9 | A10 |
| 4 | PWA | 89a9335 | A03 A10 |
| 5 | CSP and dependencies | 72a6e48 | A10 A12 |
| 6 | mock billing | 8ff8912 | A04 A07 |
| 7 | ingestion/review | 3486c2e | A05 A06 |
| 8 | local collection | e9494f7 | A06 A09 |
| 9 | HTTPS adapter | 9451e66 | A06 A09 |
| 10 | scheduler | 42c1f4c | A09 |
| 11 | reliability/restore | bdd4764 | A09 A11 |
| 12 | synthetic fixtures | 972ada3 | A02 |
| 13 | Mongolian QA | 037e783 | A08 |
| 14 | grounded mock | 5bda2b1 | A08 |
| 15 | pilot chat | 79382fb | A03 A10 |
| 16 | pilot security | f4adf9c | A01 A02 A03 A10 |
## Risk register
P0 = production blocker; P1 = high risk before relevant feature enabled; P2 = improvement before wider rollout. Static findings are design/code observations, not demonstrated exploits.
| ID | Priority | Evidence and risk | Acceptance |
|---|---|---|---|
| A01 | P0 | pilot_security.py shared code, process-local token store; 001 request_user_id reads mutable session GUC; no production identity binding. | Verify signed issuer/audience/expiry; server maps subject; transaction-local identity; revoke sessions and memberships; negative cross-tenant tests, no client-supplied actor. |
| A02 | P0 | public_api pilot guard checks DSN config only; read_public does not check actual DB marker; Next forward checks flag and loopback only, public proxy accepts configured origin. | Explicit deployment modes fail closed; pin permitted upstream; actual DB identity/marker check; separate credentials/network and deny production pilot routes; test wrong config and inherited PG env. |
| A03 | P0 | public GET bypasses pilot limiter; pilot per-session limits reset on restart, login allows repeated sessions; Next forward reads request stream before upstream timeout. | Shared atomic limits across replicas, global and principal budgets, bounded concurrent connections and request read deadline, trusted proxy configuration, 429 and load tests. |
| A04 | P0 | mock_billing.py trusted actor/resolved/date inputs; no authenticated billing service or provider reconciliation; pricing is integer MNT and mock idempotency is present. | Server-owned quote/outcome, signed sandbox callbacks, replay protection, reconciliation and refunds; no real funds until approval. |
| A05 | P0 | ingestion.py accepts reviewer UUID supplied by caller; 005 reviewer role broad SELECT/INSERT sources and UPDATE listings; same UUID check not identity proof. | Bind submit/review identities to authenticated principals, separate service roles, constrain publication transition and test forged actors, permission revocation, cross-org and direct writes. |
| A06 | P1 | review upserts by organization without observation ordering; local JSON has no publisher timestamp, checks path then opens; HTTPS timestamp publisher-asserted. | Monotonic publication under org lock, reject stale/older observations; atomic file open with trusted root/no symlink and bounded read; provenance and revocation race tests. |
| A07 | P1 | 004 ledger unique event and append-only grants but no DB-level transition/amount cross-table constraint; mock billing connects without explicit connect timeout; pure inquiry accepts truthy resolved values and allows emergency+clarification unlike mock path. | Canonical lifecycle, explicit types and conflict handling; database invariants, restricted service procedures, timeouts, property/concurrency tests and reconciliation. |
| A08 | P1 | public_api SQL name substring only; grounded_ai ranks first 20 and mock selects IDs, no real semantic answer or durable usage. Legacy listing free text can contain personal data. | Approved field-level privacy checks, freshness and source validation, offline relevance corpus (Cyrillic/Latin/category), evidence-only answer, bounded adapter deadline, persistent usage/idempotency; no invented facts, no real calls. |
| A09 | P1 | scheduler bounded child transport and shared bucket present; collect_registered default fetch_json callable bypasses child deadline if invoked directly; local Runner holds transaction during file read; HTTPS special translation ranges/egress not independently verified. | One enforced transport boundary, blocked private/translated addresses, DNS/TLS tests using mocks, local IO deadlines, multi-process recovery and network deny-by-default; real traffic only after approval. |
| A10 | P1 | PilotChat token in JS memory, logout network failure swallowed, old responses can remain until another request; pilot UI always shown; physical devices not tested. | Mode-gated UI, reliable logout/expiry state and stale request fencing, secure session design, privacy consent and retention, real-device checklist and accessibility tests. |
| A11 | P1 | backup_restore.sh disposable schema restore compares row hashes and selected ACL only, no sequence/global role/point-in-time/offsite drill. | Full restore including sequence/role grants and migration history; encrypted offsite backup, defined RPO/RTO, recovery drill and alerts. |
| A12 | P1 | requirements-public.txt broad dependency ranges; Python CI installs without hash lock; actions use version tags, npm lock present. | Reproducible Python hashes, dependency and secret scans, least-privilege CI and pinned actions, SBOM, independent review before merging. |
## Production roadmap
Do one branch/PR at a time, no merge without human approval. Keep all 97 regressions and add targeted tests. No external integration in these tasks.
- T09.2: A01/A02 identity and deployment isolation foundation, synthetic issuer and DB-only tests. Acceptance: unauthorized/forged/cross-tenant requests fail, pilot cannot open on nonpilot DB, trusted subject mapping and expiry/revocation. 
- T09.3: A03 API abuse controls and deadlines; shared PostgreSQL-backed limits, concurrency and redacted events. Acceptance: parallel workers respect shared budget, oversized/slow requests rejected.
- T09.4: A05/A06/A09 authorized collection and publication integrity; offline adapters only, newest evidence wins and revoke hides records, bounded file/HTTPS IO and network policy tests.
- T09.5: A04/A07 mock billing invariant and authenticated workflow; no external provider, replay/refund/reconciliation simulation, exact integer prices 1000/300000, no charge on failure/emergency/clarification.
- T09.6: A08/A10 grounded QA/privacy and PWA lifecycle; offline corpus, source/expiry checks, consent and retention design, browser regression and human/device checklist.
- T09.7: A11/A12 release engineering, recovery, dependency integrity, independent review and final readiness report. No deployment or merge without explicit approval.
## Decision
Pilot baseline passed, production NO-GO. P0 closure required before any public service; P1 closure before enabling affected capabilities. Independently review all PR diffs, actual deployment configuration, threat model and load tests. Separate explicit approvals required for real identity provider, authorized live sources, AI service and payment sandbox. This report does not certify security or estimate launch date.
