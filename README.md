# delmon-ai-lavlah
DELMON LAVLAH — Mongolian AI-powered information service.

## Local tests

Use Python 3.12 from the repository root. The domain model and tests use the standard library.

```sh
python -B -m unittest discover -s tests -v
```

GitHub Actions runs the same command on pushes to `develop/mvp-foundation` and on pull requests.

## Inquiry pricing

A resolved personal inquiry costs 1,000 MNT. The caller must record consent to the exact quote before resolution. Emergency information and follow-up clarifications for the same requester and case are free. A failed inquiry reports zero charge and the full authorized amount to refund or release.

The lifecycle returns immutable state and cumulative amounts per request. To apply the domain rules in a service, load the latest state by request ID and persist each transition atomically. Payment operations need a durable idempotency key for each request and operation. The domain module performs no payment operations.

Organization basic listing is free. Annual active service costs 300,000 MNT and includes catalog management, lead and RFQ intake, and analytics until the recorded expiry date. The organization inquiry allowance is pending cost measurement.

## PostgreSQL directory foundation

Run these commands against a dedicated, empty PostgreSQL 16 development database with a migration role that can create schemas and roles. The PostgreSQL workflow uses an ephemeral database.

```sh
psql -X -v ON_ERROR_STOP=1 -f db/migrations/001_directory.sql
psql -X -v ON_ERROR_STOP=1 -f tests/directory.sql
```

The tests roll back their fixtures. For an expendable database, the matching down migration removes the directory schema and its data.

The backend must resolve the verified authentication subject to an internal user ID before entering the request transaction. Set the ID with a parameterized `set_config('lavlah.user_id', ..., true)` in that transaction and run directory queries under `lavlah_request`. Keep database credentials and arbitrary SQL access server-side. The request role can read the user's profile and own memberships, and tenant records covered by those memberships. Owners and editors can edit their organization's profile and submit sources. Viewers can read their organization's records. User provisioning, membership changes, category administration, and verification require a separate trusted path.

New sources start unverified and carry a URL, authorization reference, submitter, and observation time. Source review records the verifier, verification time, and expiry. The future search API should project approved public fields and use only currently verified sources with `verified_at <= CURRENT_TIMESTAMP AND expires_at > CURRENT_TIMESTAMP`.
