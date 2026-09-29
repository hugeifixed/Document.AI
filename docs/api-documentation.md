# API documentation and agent discovery

All references describe the same OpenAPI 3.2 contract; no alternate business API or MCP server is added here.

| URL | Purpose |
| --- | --- |
| `/api/schema/?format=json` | Authoritative OpenAPI JSON (the unqualified URL also negotiates YAML) |
| `/api/docs/` | Existing, locally hosted Swagger UI |
| `/api/docs/scalar/` | Optional, locally hosted Scalar reference |
| `/api/llms.txt` | Concise agent journey: upload, invoke, poll, inspect, review, evaluate, export |
| `/api/docs/integration.md` | Detailed Markdown integration contract and examples |
| `/llms.txt` | Public discovery pointer only; no operation inventory or document information |

The separately packaged `docai-cli` adds terminal commands over this same API; it does not add endpoints or bypass
authentication and role checks. See the repository's `CLI.md` for editable installation and shell `PATH` setup.

The canonical integration guide lives in `backend/docai/docs/integration.md`. Edit that file, not a second
copy: Django packages and serves it, and root `INTEGRATION.md` links to it. The short agent guide lives in
`backend/docai/templates/docai/docs/llms.txt`; named Django routes keep its navigation aligned with deployment
prefixes. OpenAPI remains the authority for individual operations. These text views do not generate a schema
on every request, inspect documents, or contact an LLM. ReDoc and `llms-full.txt` are intentionally deferred.

## Access and presentation

Swagger, Scalar, and both detailed text guides share Spectacular's configured authentication and permission
classes. Deployed settings require authentication; local documentation remains available for development.
Authenticated documentation is `private, no-store`. Root discovery is deliberately generic and public.
An agent must supply the same session/CSRF or explicitly enabled HTTPS Basic authentication as an API client.
`llms.txt` does not grant access or guarantee that an agent automatically discovers or follows it.

Scalar uses the DocAI favicon, local font and light/dark palette. Its request client includes same-origin
session cookies and the Django CSRF token on unsafe requests. Cross-origin requests and redirects are rejected;
credentials are not persisted. Scalar telemetry, default remote fonts, hosted AI agent, generated-MCP promotion,
external client links and developer tools are disabled. A same-origin content security policy also limits network
connections. There is no external Scalar request proxy. The vendor UI is not a blanket WCAG certification;
verify keyboard behavior and contrast again when upgrading the bundle.

## Enable Scalar without a CDN or extra runtime dependency

Scalar is off by default (`DOCAI_SCALAR_ENABLED=false`). Its self-contained browser bundle is an optional build
asset, not a dependency of the React app or a new Python package. Django, Swagger and agent guides work without it.

The admitted version is `@scalar/api-reference@1.68.0`, published **2026-09-07**. Obtain its original npm tarball
through the institution's approved registry/Artifactory. On a connected development machine, from the repository
root (the same commands work in PowerShell and POSIX shells):

```text
npm pack @scalar/api-reference@1.68.0 --ignore-scripts --pack-destination backend/data
python scripts/install_scalar.py backend/data/scalar-api-reference-1.68.0.tgz
```

Create `backend/data` first if it does not exist. In an isolated build, supply that tarball as an approved artifact
and run only the second command. The installer is offline, verifies the pinned SHA-512 npm integrity, and copies
only the named standalone JS member; it does not extract arbitrary archive paths or install transitive build
dependencies. The upstream bundle includes its compiled dependencies. Scan the supplied artifact with the
institution's normal artifact admission tooling.

Set `DOCAI_SCALAR_ENABLED=true` in the backend process environment or ignored local `.env`, then restart Django.
For deployment, install the asset **before** packaging the backend and running `collectstatic`. The installed
asset is intentionally ignored by Git and is included in Python package data when present. The runtime image
must retain the package's static source as well as publish the collected static output. If enabled without the
asset, Scalar returns a useful `503` page linking to Swagger; it never falls back to a CDN.

To disable/remove Scalar, set the flag to false and remove `backend/docai/static/docai/vendor/scalar/` plus its
collected assets during a clean build. No dependency uninstall, database migration, or frontend change is needed.

### Controlled upgrades

Select a release older than seven full days, obtain it from the approved registry, review its release notes,
and update the pinned version/integrity in `scripts/install_scalar.py` and the versioned asset path in
`backend/docai/api/documentation.py`. Update this guide. Verify the actual OpenAPI 3.2 schema renders, files upload,
session/CSRF and Basic authentication still work, no external requests occur, and keyboard/light/dark behavior
remains usable. Run normal verification plus the browser documentation smoke test described below.

## Routing and deployment

Vite proxies `/api/*`, `/static/*`, and the exact `/llms.txt` path to Django. On OpenShift or another reverse proxy,
route those paths to Django/static hosting **before** the React SPA fallback; otherwise agents receive HTML.
Honor the configured application mount prefix. Use Django's trusted-proxy settings for HTTPS links, rather than
embedding environment hostnames. The documentation and Scalar assets do not use the NAS document store.

Run `python scripts/verify.py` for normal gates. Browser checks for documentation should load Django's live docs
with Scalar enabled and the local asset installed, in both themes and desktop/tablet widths. Check schema load,
local-only network activity, keyboard navigation, and a session-authenticated mutation with real CSRF enforcement.
The Scalar navigation stays sticky; its measured height feeds Scalar's custom-header offset so the sidebar's
theme toggle fits the remaining viewport. Check the toggle without scrolling, including after resizing and
opening the mobile menu when navigation links wrap.
