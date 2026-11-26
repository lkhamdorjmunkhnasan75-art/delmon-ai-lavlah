# T10.3.1 — Identity boundary hardening
Base ed471f4, PR 26; 155 previously verified tests on 4053b94. Target 165 distinct tests (95 unit/API, 58 database, 12 browser); CI pending.

Changes: checked_dsn rejects missing/malformed configuration with generic ValueError, requires explicit pilot mode and opt-in, numeric loopback and expected database/login, port 5432, valid sslmode and no inherited routing variables (even empty). identity_transaction explicitly pins TCP address and port. Actual connection check rejects missing TCP server address. Existing signed synthetic token verification, role switch, per-token revocation lock and RLS remain unchanged.

Six new preflight tests and four isolated PostgreSQL tests cover successful preflight, wrong/missing mode and settings, malformed/wrong DSN before connecting, inherited routing, non-TCP connection, cross-tenant read/update denial with positive own-tenant update, viewer read-only, committed membership deletion with same token, direct unauthorized membership insert. CI explicitly executes the DB suite. Existing tests and secret gate unchanged.

## Integrated audit and residual risks
A01: RLS trusts transaction-local identity set by trusted service; direct SQL access to that login remains privileged within granted roles. No arbitrary SQL API should be exposed. Membership deletion is tested after commit, not a concurrent revocation guarantee. Real issuer, role hardening and DB write boundary remain open.
A02: explicit synthetic identity mode and DSN boundary hardened; other legacy service paths, deployment startup mode, physical cluster isolation and inherited libpq settings need independent review.
A05: authenticated ingestion binds actor to token; current permission advisory lock does not automatically serialize administrator updates or deletes, and direct reviewer DB grants remain broad. Next small task: review transaction-level revocation synchronization and narrow direct write grants with tests.
No new provider, network source, payment or production deployment. No main change or merge. A12 secret gate remains blocked without waiver; production NO-GO. Test counts are targets until CI logs confirm.
