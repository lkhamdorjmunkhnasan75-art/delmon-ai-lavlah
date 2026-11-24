# Public directory
Apply migration 001 then 002 in an expendable development database.
Install requirements-public.txt and run python -B -m unittest discover -s tests -v.
Start with uvicorn lavlah.public_api:app using a server-only LAVLAH_PUBLIC_DSN.
The dedicated login must have membership only in lavlah_public_reader, no ownership or superuser privileges. Do not reuse tenant credentials.
GET /v1/directory accepts q (literal case-insensitive name substring), category (slug), limit (1–100), offset (0–10000).
A trusted reviewer approves a public snapshot and explicitly approves a public source URL; never publish private URLs, authorization references or user data. No automatic approval. A source must be currently verified and match the organization and approved URL. Revocation removes visibility. Tenant edits do not change the approved snapshot.
This endpoint is anonymous and read-only; future tenant endpoints require verified identity per T03. Production requires rate limiting, TLS, credential provisioning, reviewer workflow and security review. No deployment or live data is authorized.
Rollback migration 002 before 001.
