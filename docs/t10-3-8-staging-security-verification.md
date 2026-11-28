# T10.3.8 staging security and independent verification

Baseline: df156a7ab837d8135c75cf3efb83b842b1ef0a36, the head of [Draft PR #33](https://github.com/lkhamdorjmunkhnasan75-art/delmon-ai-lavlah/pull/33). GitHub Actions logs show 101 passing and 82 skipped Python tests, plus 160 passing PostgreSQL job tests, including 12 browser tests. Deduplicating successful unittest IDs yields 195, with 66 shared between jobs.

| Baseline evidence | Source |
| --- | --- |
| Unit discovery, hash-locked install and Python advisory check | [Python job](https://github.com/lkhamdorjmunkhnasan75-art/delmon-ai-lavlah/actions/runs/46071657893/job/140749781002) |
| Migration 019 up/down/up, reviewer ACL and revocation regressions, disposable backup/restore | [PostgreSQL job](https://github.com/lkhamdorjmunkhnasan75-art/delmon-ai-lavlah/actions/runs/46071657955/job/140749780621) |
| Repeatable hash-only installs, dependency audit, CycloneDX SBOM, history scan | [Supply chain job](https://github.com/lkhamdorjmunkhnasan75-art/delmon-ai-lavlah/actions/runs/46071657884/job/140749780457) |

[Baseline evidence artifact 15233152444](https://github.com/lkhamdorjmunkhnasan75-art/delmon-ai-lavlah/actions/runs/46071657884/artifacts/15233152444) was published for the baseline SHA. GitHub lists SHA-256 `aed106b031b1e60023a2eb8677727bdaa2f426ef736c6632cd345c1214ee2915` and expiry on 2026-12-04 UTC. The log reports 155 tracked files with zero matches and 347 reachable historical blobs with two reviewed reserved-test-host URL matches. An independent reviewer should verify the archive digest, SBOM against both lockfiles, the two history decisions within their recorded scope, and the effective workflow approval and branch protection rules. Record the reviewed SHA, UTC timestamp, evidence links and reviewer sign-off.

## Database permission evidence to collect

Staging is unverified. The connected Supabase account did not list an identified Delmon Lavlah staging project. The repository implements a synthetic pilot with explicit loopback and database identity checks. Obtain the confirmed staging project and database identifiers, build SHA, and approved worker and operator access paths before running a database check.

From a read-only staging audit session, collect PostgreSQL version and effective database settings, login attributes and transitive role memberships, schema/table/column/function grants including PUBLIC and default ACLs, definer owners and configured search paths, role/database setting overrides, RLS policies, and prepared-transaction count. Query effective access as the actual reviewer worker identity where applicable. Collect separate positive worker and negative non-worker network and secret-access evidence. Redact connection strings and tokens.

```sql
BEGIN READ ONLY;
SELECT current_database(), current_setting('server_version');
SELECT name, setting, unit, source, pending_restart
FROM pg_settings
WHERE name IN ('max_prepared_transactions', 'transaction_timeout',
               'lock_timeout', 'idle_in_transaction_session_timeout', 'statement_timeout')
ORDER BY name;
SELECT count(*) FROM pg_prepared_xacts;
ROLLBACK;
```

| Control | Evidence and expected outcome |
| --- | --- |
| Reviewer isolation and least privilege | Distinct reviewer and collector logins and secret access policies. Only the approved worker can reach the reviewer SQL route. No role elevation, direct protected writes, cross-tenant access, or helper execution outside the documented ACL. Capture the role graph and ACL results. |
| Emergency revocation | Exercise a disposable staging principal on both a fresh and an existing session. Record cutoff latency, operator authority to terminate only the matching reviewer backends, committed binding removal, denial of new work and absence of partial writes. |
| Transaction, lock and idle transaction timeouts | Record each effective setting on a fresh reviewer connection and measure each limit separately. PostgreSQL 16 has no transaction_timeout setting. If an external deadline provides that bound, verify server-side cancellation or disconnect and rollback. Check whether worker-accessible session overrides affect the bound. |
| SET CONSTRAINTS | Establish that clients outside the worker cannot control reviewer transactions. Migration 019 uses a deferrable check and depends on worker isolation for transaction control. Obtain an independent review of that assumption. |
| PREPARE TRANSACTION | Confirm no dependency on two-phase commit, effective max_prepared_transactions=0, no pending restart, and zero prepared transactions. Run the harmless denial check on a disposable fixture. |
| REVOKE | Baseline CI checks membership revocation during review. On staging, validate effective membership removal and behavior of fresh and already admitted work using a disposable principal. |
| NOLOGIN | Verify group and definer roles cannot log in. Separately verify new connections are denied after disabling a disposable reviewer login and existing sessions are terminated by the emergency procedure. |
| Token expiry | Verify expired admission is denied without a reviewer connection. Independently assess the in-flight lifetime and real issuer semantics. The synthetic identity and reviewer transaction use separate connections. |

Required access is a staging-scoped read-only catalog session, controlled access to the synthetic reviewer fixture through the worker, a non-worker vantage point for network and secret isolation evidence, and an authorized operator for the disposable revocation drill. The configuration owner must confirm the two-phase-commit dependency and any server settings requiring restart. Perform drills on resettable synthetic data.

A01, A02, A05 and A12 remain open pending staging evidence and independent sign-off. The interval between the final authorization check and durable commit remains an open risk. Production remains NO-GO.
