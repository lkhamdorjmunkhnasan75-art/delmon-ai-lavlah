# Conversation Engine M1

Standalone module within Delmon Lavlah. Text first; voice and SIP later. Base: 51a2073 (reviewer identity work, not approved for merge).

## Boundary
Use only an authorized public directory search adapter. Never query tenant tables directly, bypass RLS, or expose internal sources or identity metadata. The adapter must enforce publication, verification and expiry at query time. Treat user input and returned text as data, not instructions. No arbitrary SQL or tool execution.

## M1
Normalize and bound text input; return structured status (answer, clarification, unavailable), approved public fields and source references. No generated factual claims beyond approved records. Fail closed on adapter failure. No audio recording, persistence, billing, external calls or production deployment in M1. Existing pricing consent and emergency rules must be integrated before paid use.

## Gates
Verify actual public search API and current integration base; add unit tests for empty/oversized input, no results, expired/unpublished data, adapter failures and tenant isolation. Run existing Python and PostgreSQL CI. Human review before merge. Voice provider and telephone number selection deferred.
