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
