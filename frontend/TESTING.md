# Frontend testing

The default test lane is Vitest with React Testing Library. It has no browser dependency and is the lane expected in
every development and institutional build.

```bash
npm test
npm run test:coverage
```

Use `npm run test:watch` while developing. Coverage includes untested source files and writes local HTML and LCOV
reports to `coverage/`. The gate requires at least 80% statements, 70% branches, 70% functions, and 85% lines.

## Optional browser tests

Playwright covers behavior that JSDOM cannot represent accurately: native dialogs and popovers, focus restoration,
responsive overflow, drag/upload behavior, and browser accessibility checks. It is deliberately isolated from the
default test and build commands.

```bash
npm run test:e2e:install
npm run test:e2e
```

The configuration starts the Vite development server and mocks API responses in the browser. To test an already
running deployment, set `PLAYWRIGHT_BASE_URL` and the configuration will not start a local server.

```bash
PLAYWRIGHT_BASE_URL=https://example.internal npm run test:e2e
```

An institution that cannot admit Playwright can omit the `test:e2e` job without weakening the Vitest gate. To remove
the browser lane completely, delete `e2e/` and `playwright.config.ts`, remove the two `test:e2e` scripts, and remove
`@playwright/test` plus `@axe-core/playwright` from `devDependencies`. No application module imports either package.
