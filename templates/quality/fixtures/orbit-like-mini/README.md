# Orbit-like mini fixture (AGE-31)

Synthetic stand-in for a TS app with Playwright + SQL migrations/pgTAP.
**Not** a copy of Orbit product code — local fixture only for detection / gate demos.

Markers present:

- `playwright.config.ts` + `@playwright/test` in `package.json` + `e2e/smoke.spec.ts`
- `db/migrations/001_init.sql` + `db/tests/test_init.sql` (pgTAP-style)

Agentized auto-detects both layers (`e2e.enabled=auto`, `db_tests.enabled=auto`).
Changing `src/**` without updating `e2e/**`, or `db/migrations/**` without `db/tests/**`, fails the hard gate.
