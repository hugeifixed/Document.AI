# Standalone DocAI CLI

Provide a first-class terminal client for people, services, and agents that reuses the
headless REST API as its only application boundary. Keep the CLI separately installable
and independent of Django so it does not duplicate authorization or workflow rules and
can later adopt another credential provider without changing command behavior.

## Acceptance

- Use a standalone Python package and a discoverable `docai` entry point; do not import
  Django, access application models, or introduce a parallel service layer.
- Expose a small, useful API surface for health, identity, projects, datasets, workflows,
  uploads, run submission/status/progress/wait/cancel/retry/export, and review queues.
- Keep output automation-safe: `--json` emits one JSON object on stdout; human progress
  and errors go to stderr; list output preserves full IDs; exit codes distinguish usage,
  validation, auth, not-found, API, timeout, and transport failures.
- Poll asynchronous runs through the existing result-manifest endpoint, honor ETags and
  `Retry-After`, bound polling with a timeout, and retain the run handle after timeout.
  Require/replay the API's idempotency key for submission; never blindly retry writes.
- Stream uploads and exports. Preserve accepted/reused/rejected upload details on partial
  failure and avoid publishing incomplete export files.
- Use current session authentication by default and HTTPS-only Basic only where enabled
  by the server. Never accept passwords as command arguments or disable TLS verification.
  Keep credential acquisition behind the HTTP client boundary for future OIDC support.
- Provide shell-install instructions so `docai` can be available on PATH, alongside the
  project-scoped `uv run --project cli docai ...` form.
- Keep examples thin wrappers around the CLI. Integrate CLI lint, type, test, coverage,
  and wheel-build checks without coupling CLI setup to the backend virtual environment.
- Update onboarding, architecture, integration, and API-discovery documentation.

## Decisions

- Use standalone Typer rather than Django Typer because every command is an HTTP client;
  Django's management-command lifecycle is not needed and would couple the CLI to the
  web application package.
- Keep the REST API as the single authorization and business-logic boundary. Add an API
  operation only when the CLI needs a capability not already exposed there.
- Keep one command package and one HTTP client module until concrete growth calls for
  further decomposition. Rich is limited to human terminal presentation; JSON stays
  ordinary, compact JSON.

## Local task graph

1. Add the independent package, command groups, safe HTTP/auth/output behavior, and tests.
2. Route example invocation helpers through the CLI and update docs and repository checks.
3. Verify installation, CLI contracts, project quality gates, and review against this spec.
