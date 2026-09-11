# Frontend testing

The default test lane is Vitest with React Testing Library. It has no browser dependency and is the lane expected in
every development and institutional build.

```bash
npm test
npm run test:coverage
```

Use `npm run test:watch` while developing. Coverage includes untested source files and writes local HTML and LCOV
reports to `coverage/`. The gate requires at least 80% statements, 70% branches, 70% functions, and 85% lines.

## Optional browser integration tests

Playwright covers behavior that JSDOM cannot represent accurately: native dialogs and popovers, focus restoration,
responsive overflow, drag/upload behavior, and browser accessibility checks. The suite has its own package manifest
and lockfile under `e2e/`; the normal frontend install, test, and build commands do not install or invoke Playwright.

```bash
npm run test:browser:setup
npm run test:browser
```

Setup installs only the isolated browser-test dependencies and Chromium. By default, the test configuration builds
the frontend and serves the production bundle with Vite Preview. Every API response remains mocked in the browser so
the tests are deterministic and do not require Django.

To run the same mocked browser tests against frontend assets from an already-running deployment, set
`PLAYWRIGHT_BASE_URL`. This mode does not validate its backend, authentication cookies, CSRF, CORS, or proxy routing.

```bash
PLAYWRIGHT_BASE_URL=https://example.internal npm run test:browser
```

These are browser integration tests, not live end-to-end tests. A future live test lane should use a separately seeded
environment and must not install API routes from `e2e/support/`.

An institution that cannot admit Playwright can omit the browser-test setup and job without weakening the Vitest
gate. To remove the browser lane completely, delete `e2e/` and remove the two `test:browser` scripts from the parent
`package.json`. No application or normal frontend development dependency imports Playwright or Axe.
