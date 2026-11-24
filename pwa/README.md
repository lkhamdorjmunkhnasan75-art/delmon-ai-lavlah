 # DELMON LAVLAH PWA

Run the existing FastAPI backend with its restricted database login. In this directory use `npm install`, then `npm run build` and `LAVLAH_API_ORIGIN=http://127.0.0.1:8000 npm start`. Production requires HTTPS and a trusted, server-only upstream URL. Never put database credentials in Next.js client variables.

The original FastAPI HTML UI remains available on its own port. PWA uses network-only requests and does not cache directory records. Browser installation availability varies; test manifest and worker in CI, and manually verify install on Android and iOS before release. Unknown category slugs fall back to a visible slug. CSP currently permits inline scripts for Next hydration; nonce-based hardening remains a release task. Generate and review a dependency lockfile before release. No production deployment authorized.
