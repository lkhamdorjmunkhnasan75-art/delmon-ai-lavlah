# DELMON LAVLAH — MVP release readiness
## Decision: NO-GO for public production
Baseline: T08.4 verified 89 distinct tests and backup/restore on 1a32bec. T08.5 verified on 9616a1b: 97 distinct tests (53 unit/API, 33 database, 11 browser), all passed; Python CI 45605354317 and PostgreSQL CI 45605354315. All eight security tests and five authenticated chat browser tests passed. Backup/restore table data and selected ACL checks passed; npm audit reported zero vulnerabilities. Pilot scope complete; production remains NO-GO. No public deployment authorized.

## Implemented pilot controls
- Synthetic shared access code from server environment, minimum 24 characters; constant-time comparison; random 256-bit session token, SHA-256 digest stored in process memory; 15-minute expiry and logout.
- Pilot endpoints require session except login, exact pilot environment, loopback restricted DB login/DB name, and loopback client. Next proxy pins browser Origin/Host and forwards only fixed actions to loopback. Use uvicorn --no-proxy-headers --no-access-log.
- Global login limit 10/minute; per-session request limit 20/minute; bounded in-memory rate/session maps; restart clears both. Not a distributed limiter.
- 4096-byte pilot body limit, five-second backend body read deadline, generic validation errors, no-store responses, numeric mock usage and categorical security events. No passwords, tokens, questions or identity in security event logs.
- Browser token and feedback in memory only; no real identity or customer data. Pilot access code is not a production account, registration, tenant authorization or MFA.

## Release blockers
| Gate | Status |
|---|---|
| New security CI and backup/restore | Passed in disposable pilot CI |
| Independent security review and stacked PR review | Pending |
| Real identity provider, account lifecycle, tenant roles and revocation | Blocked |
| Distributed rate limits and abuse/load testing | Blocked |
| TLS, trusted proxy configuration, dedicated DB/network/egress isolation | Blocked |
| Secret management, log retention/redaction and alerts | Blocked |
| Consent, privacy policy, deletion/export and persistent feedback | Blocked |
| Physical Android/iOS and human pilot | Blocked |
| Authorized real sources and validated model integration | Blocked |
| Real payment provider sandbox and reconciliation | Blocked |
| Offsite encrypted backup and disaster recovery drill | Blocked |

Public directory GET remains public by design; production traffic limits not implemented. Pilot DSN checks are configuration guards, not physical isolation. Synthetic password must be unique per pilot run. No public production use until independent approval. No live AI, source access, payment or main merge.
