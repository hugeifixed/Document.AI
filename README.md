# DocAI Platform

Enterprise document AI platform for **unbundling, classification, extraction, labeling, review, and evaluation**
of banking documents. Django 5.2 reusable sub-application (`backend/docai`) + React 19 / Vite 8 / Tailwind 4 / daisyUI 5
frontend (`frontend/`).

- OCR / layout: **Azure AI Document Intelligence** (prebuilt-layout) — the only OCR engine.
- PDF manipulation: **pypdf** only. Excel: openpyxl / xlrd (never evaluates macros or formulas).
- LLM: Azure-hosted GPT through **LangChain + Pydantic structured output**, authenticated with
  **DefaultAzureCredential** (`az login` locally, managed identity deployed). DI and Azure OpenAI also
  support optional resource keys for temporary local testing.
- Runs locally with **no Azure access at all**: the `pypdf` layout adapter reads text-layer PDFs and the
  deterministic `mock` LLM adapter satisfies the same Pydantic schemas a real model must — the full
  pipeline, metrics, review, labeling and exports all work offline on synthetic documents.

### Start here

| Reader | First document | Then read |
| --- | --- | --- |
| New developer | This quickstart | [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`backend/env/README.md`](backend/env/README.md) |
| Frontend developer | [`frontend/DESIGN.md`](frontend/DESIGN.md) | [`frontend/ARCHITECTURE.md`](frontend/ARCHITECTURE.md) |
| Integration developer | [`INTEGRATION.md`](INTEGRATION.md) | Interactive OpenAPI documentation at `/api/docs/` |
| Workflow author / business administrator | [Copy-and-paste workflow JSON](examples/workflows/README.md) | Pick a type, paste an example, validate and create a version |
| Operator | [`backend/CELERY.md`](backend/CELERY.md) | Deployment and health sections below |
| Coding agent | [`AGENTS.md`](AGENTS.md) | Root and frontend architecture documents |

[`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) states what is not yet ready for a broader security boundary.

---

## Quickstart (local, keyless)

Prerequisites: Python 3.11.4 or 3.12, `uv`, Node 20.19+ or 22.12+, and npm 10 or 11. The repository records
npm 11.6.0 as its package manager; the supported Node releases include a compatible npm version.

POSIX shells (macOS/Linux):

```bash
# backend
cd backend
uv sync --extra dev
cp env/local.env.example .env
uv run python manage.py migrate
uv run python manage.py seed_defaults --admin-password admin123
uv run python manage.py make_synthetic_data --build-layouts
uv run python manage.py run_sample
uv run python manage.py runserver 8000

# frontend (second terminal)
cd ../frontend
npm ci
npm run dev # http://localhost:5173; proxies Django routes to :8000
```

PowerShell (Windows):

```powershell
Set-Location backend
uv sync --extra dev
Copy-Item env/local.env.example .env
uv run python manage.py migrate
uv run python manage.py seed_defaults --admin-password admin123
uv run python manage.py make_synthetic_data --build-layouts
uv run python manage.py run_sample
uv run python manage.py runserver 8000

# frontend (second terminal)
Set-Location frontend
npm ci
npm run dev
```

Open `http://localhost:5173/` to reach the central sign-in page (seeded account: admin / admin123).
The frontend and Django admin share a Django session. After sign-in, you return to the page you requested;
use **Log out** in the frontend header to end the session. Expired sessions return to sign-in automatically.
Pick the **Sample banking documents** project and **synthetic-dev** dataset in the sidebar.

In **Runs → Start a run**, leave **Document limit** blank to include all eligible documents, or
enter a limit to take the oldest eligible uploads first. **Choose documents** opens a searchable
multi-select dialog for an exact selection; applying it clears the limit. Validated, processed
and failed documents are eligible. Changing the dataset clears the selection.

API docs: `http://localhost:8000/api/docs/` (OpenAPI 3.2). Human-readable system status:
`http://localhost:8000/health/`; machine probes: `/health/live/` and `/health/ready/`.

For local request and SQL profiling, set `DJANGO_SILKY_ENABLED=true`, run
`.venv/bin/python manage.py migrate`, restart Django, and open
`http://localhost:8000/admin/profiler/` as a superuser. Set the variable back to `false` and restart
to remove the middleware, routes, and profiler models from the running application. Request and response
bodies are never stored; `DJANGO_SILKY_MAX_RECORDED_REQUESTS` defaults to 2,000 metadata records. When enabled,
the frontend account menu, admin home, and admin Operations section provide a direct **Request profiler** link.
Named profiles highlight document uploads, layout generation, run dispatch and retries, segmentation changes,
field and classification review, and evaluation. To avoid profiler writes competing with frontend polling on SQLite,
Silk records API mutations and skips GET/HEAD polling. The decorators are no-ops when Silk is disabled. With the
Celery runner, Silk measures HTTP validation and task dispatch; worker-side DI and LLM duration remains available
through `RunItem.duration_ms` and structured worker logs because Celery work runs outside the originating request.

Expected output of `run_sample` with the mock adapter (synthetic dev set):

```
status=succeeded processed=18 failed=0
extraction: acc=0.9577 P=1.0 R=0.9577 F1=0.9784 ...   # per-field taxonomy table follows
classification: acc=0.9333 macroF1=0.8333             # the one miss is the intentionally unconfigured invoice → other
segmentation: boundaryF1=1.0 pageAcc=1.0 exact=1.0 docs=2
```

For every optional backend integration, run `uv sync --all-extras`. Dependencies are pinned in
`pyproject.toml`; uv applies the seven-day cutoff and installs only packages needed by the current
platform. Its generated `backend/uv.lock` is local and intentionally ignored. Worker and admin-panel
tests do not require a running broker.

From the repository root, `python scripts/verify.py` runs the offline backend and frontend quality gates.
Use `--backend` or `--frontend` for one side. `--browser` adds the optional Playwright Chromium suite;
it is intentionally excluded from the default gate.

Dependency updates must satisfy the institutional seven-day quarantine. Python resolution is enforced by
`tool.uv.exclude-newer`: update the exact pin in `pyproject.toml`, run `uv sync --all-extras`, and validate on both
supported Python versions. Do not commit the generated `backend/uv.lock`; Artifactory is authoritative in the
institution. For npm, choose a release published more than seven days earlier, update `package.json`, regenerate
and commit `package-lock.json`, and verify with `npm ci`. The verification script never installs or resolves
packages, so routine checks remain offline after setup.

`npm ci` in `frontend/` installs the locked dependencies and the repository's Husky dispatcher. It keeps the two commit gates isolated:
frontend-only changes run `npm run check:pre-commit` (Oxlint and TypeScript), while backend changes run the Python
checks in `.pre-commit-config.yaml`. A commit touching both areas runs both gates. Run either gate directly with
`cd frontend && npm run check:pre-commit` or
`uv run --project backend --isolated --extra dev pre-commit run --all-files` from the repository root. The backend
gate validates the hook configuration and Python metadata, checks file hygiene and secrets, applies safe Ruff and
Django 5.2 upgrades, checks Django-aware types, and requires 80% combined statement/branch coverage. It writes
`backend/coverage.xml` for the institutional Sonar scan. Sonar remains the authoritative CI quality gate, so no
server URL or token is required for a local commit.

---

## Headless integrations

Applications and agents use the same versioned REST API described by OpenAPI 3.2. The supported flow is to inspect
an approved workflow's `/contract/`, upload files to a dataset, invoke that pinned workflow with the returned
document IDs and a required `Idempotency-Key`, then poll the bounded run manifest. Successful acceptance and replay
always return `202`; result collections are paginated and complete delivery packages remain available through export
links. `client_reference` carries an upstream job or case identifier without changing DocAI's run identity.

The idempotency key is guaranteed for 30 days. Identical retries return the original run, changed input returns a
stable conflict, and a retryable dispatch failure can be resubmitted with the same key without duplicating documents
or runs. Dataset upload treats byte-identical content in the same dataset as a successful reuse (`200`) and reports
its existing UUID in `reused_document_ids`.

See [`INTEGRATION.md`](INTEGRATION.md) for the request/response contract and Python client. Current RND callers use
Django session authentication or explicitly enabled HTTPS Basic authentication. Views authorize `request.user`,
which keeps processing contracts independent of a later Entra/OIDC authenticator. MCP, webhooks, staged Blob upload,
and published SDKs are deferred.

---

## Using real Azure services

1. **Identity.** Use a service principal by supplying `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and
   `AZURE_CLIENT_SECRET` (the secret value) through your environment/secret store. `DefaultAzureCredential`
   reads these automatically; no Django settings or code changes are required. Alternatively, locally run
   `az login` (or `az login --tenant <id>`), or assign a managed identity when deployed.
   Grant it **Cognitive Services User** on the Document Intelligence resource and
   **Cognitive Services OpenAI User** on the Azure OpenAI resource. See the
   [environment authentication guide](backend/env/README.md#azure-service-principal) for setup and restart details.
2. **Endpoints** (in `.env`):
   ```
   DOCAI_LAYOUT_ADAPTER=azure_di
   DOCAI_LLM_ADAPTER=azure_openai
   AZURE_DI_ENDPOINT=https://<your-di>.cognitiveservices.azure.com/
   AZURE_DI_API_VERSION=2024-11-30
   AZURE_OPENAI_ENDPOINT=https://<your-aoai>.openai.azure.com/
   AZURE_OPENAI_API_VERSION=2024-10-21
   AZURE_OPENAI_DEPLOYMENT=gpt-5.2
   ```
3. **Model swap** = change the deployment name in a `ModelConfiguration` / workflow `model.deployment`
   (or the env default). Workflow logic never changes; every run records the deployment it used.
4. **Timeouts / retries**: `AZURE_TIMEOUT_S`, `AZURE_MAX_RETRIES`. Throttling (429) and timeouts retry with
   backoff; permanent 4xx responses (including 404), authentication failures, and unexpected local
   errors do not. Correct endpoint/model configuration before manually retrying those failures.

For temporary local testing, set `AZURE_DI_API_KEY` and/or `AZURE_OPENAI_API_KEY` in the ignored
`backend/.env`, using a key from each corresponding resource. Only `config.settings.local` reads them;
RND/UAT/QA/production and test settings keep identity authentication. Each nonempty local key takes
precedence for its service; clear it and restart to return to identity. Restart both Django and Celery
with local settings after credential changes. Keys stay outside workflow configuration and run snapshots.

The LLM adapter continues to use LangChain's versioned `AzureChatOpenAI` client. Set
`AZURE_OPENAI_ENDPOINT` to the resource root (for example, `https://your-resource.openai.azure.com/`),
without `/openai/v1` or `/chat/completions`. Set the resource-supported dated `AZURE_OPENAI_API_VERSION`
(for example, `2025-01-01-preview` when supplied by your deployment's sample) and its deployment name.
The new workflow builder initializes its editable deployment from `AZURE_OPENAI_DEPLOYMENT`;
when unset or blank, the default is `gpt-5.2`. This must match an actual Azure deployment name.
Leaving the workflow name blank uses the document/schema and workflow-type suggestion; reusing a
name creates the next version in that project's workflow family.

The workflow's `model.deployment` overrides `AZURE_OPENAI_DEPLOYMENT`, so update the workflow when
switching models. The model name is also passed to LangChain for model-specific parameter handling.
For DI testing without a real LLM, select `model.adapter: "mock"` in the workflow; an existing
workflow's adapter overrides the environment default.

The adapter rejects a full API URL with nonretryable `AZURE_ENDPOINT_INVALID` before building the
client. `AZURE_404` means the configured resource or deployment was not found; check the root URL,
deployment name, and API version, then restart the worker before retrying.

Documents that _require_ Azure DI: images (JPEG/PNG/TIFF), DOCX, and image-only (scanned) PDFs.
With the local `pypdf` adapter those are rejected with `LAYOUT_ADAPTER_UNSUPPORTED` rather than silently
producing empty results.

Optional **scan enhancement** prepares difficult image pages before DI in the existing worker. It is disabled
by default and requires the `image-normalization` extra, `DOCAI_IMAGE_NORMALIZATION_ENABLED=true`, and an
adaptive workflow. Originals and historical review sources remain immutable. See
[`backend/IMAGE_NORMALIZATION.md`](backend/IMAGE_NORMALIZATION.md) for Windows/macOS/Linux setup,
fallback warnings, independent DI high-resolution OCR, and the RND/QA quality comparison before rollout.

---

## Environment model

| Environment     | Django settings              | Deployment-supplied differences                          |
| --------------- | ---------------------------- | -------------------------------------------------------- |
| Local           | `config.settings.local`      | SQLite, local adapters, thread runner                    |
| RND             | `config.settings.production` | RND database, endpoints, hosts, storage, and credentials |
| UAT             | `config.settings.production` | UAT database, endpoints, hosts, storage, and credentials |
| QA              | `config.settings.production` | QA database, endpoints, hosts, storage, and credentials  |
| Production      | `config.settings.production` | Production infrastructure and credentials                |
| Automated tests | `config.settings.test`       | In-memory database, mocks, synchronous execution         |

The deployed environments share one fail-closed settings module to prevent stage-specific behavior drift.
Use the matching secret-free template in [`backend/env/`](backend/env/README.md); deployment tooling supplies
the real values and sets `DJANGO_SETTINGS_MODULE` before Python starts.

---

## Configuration reference (environment variables)

| Variable                                                                                                                           | Default                                                                   | Purpose                                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `DOCAI_ENVIRONMENT`                                                                                                                | `local`                                                                   | validated deployment identity: `local`, `rnd`, `uat`, `qa`, or `prod`; tests force `test`                         |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`                                                                        | dev values                                                                | production requires a unique 50+ character secret and explicit hosts; production always forces debug off          |
| `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_TRUST_X_FORWARDED_PROTO`                                                                     | true / false in production                                                | HTTPS redirect; trust the forwarded-proto header only behind a proxy that strips client-supplied copies           |
| `DJANGO_SECURE_HSTS_SECONDS`, `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_SECURE_HSTS_PRELOAD`                                | 3600 / false / false in production                                        | staged HSTS controls                                                                                              |
| `DOCAI_ENABLE_BASIC_AUTH`                                                                                                          | false in production                                                       | opt in to HTTP Basic authentication; use only over HTTPS                                                          |
| `DATABASE_URL`                                                                                                                     | `sqlite:///data/docai.sqlite3`                                            | any `dj-database-url` URL; deployed examples use Oracle `oracle://…`                                              |
| `DOCAI_DATA_DIR`                                                                                                                   | `backend/data`                                                            | media (originals, artifacts), logs, exports                                                                       |
| `DOCAI_LAYOUT_ADAPTER`                                                                                                             | `pypdf`                                                                   | `azure_di` \| `pypdf` \| `fixture`                                                                                |
| `DOCAI_LLM_ADAPTER`                                                                                                                | `mock`                                                                    | `azure_openai` \| `mock` (a `mock` environment never reaches Azure, even if a workflow says `azure_openai`)       |
| `DOCAI_TASK_RUNNER`                                                                                                                | `thread`                                                                  | `sync` \| `thread` \| `celery`; HTTP work is accepted asynchronously for every runner                            |
| `DOCAI_MAX_WORKERS`                                                                                                                | 4                                                                         | documents processed concurrently inside one thread-runner run; SQLite uses one                                   |
| `DOCAI_IDEMPOTENCY_RETENTION_DAYS`                                                                                                 | 30                                                                        | guaranteed replay window for headless invocation keys                                                             |
| `DOCAI_INVOCATION_LEASE_SECONDS`                                                                                                   | 60                                                                        | short database lease for recovering interrupted headless acceptance or dispatch; must be positive                 |
| `DOCAI_MAX_UPLOAD_MB`, `DOCAI_MAX_PAGES`, `DOCAI_MAX_SHEETS`, `DOCAI_MAX_BATCH_FILES`                                              | 100 / 500 / 50 / 500                                                      | ingestion limits                                                                                                  |
| `DOCAI_MAX_ARCHIVE_MEMBERS`, `DOCAI_MAX_ARCHIVE_MEMBER_MB`, `DOCAI_MAX_ARCHIVE_EXPANDED_MB`, `DOCAI_MAX_ARCHIVE_COMPRESSION_RATIO` | 2000 / 64 / 256 / 100                                                     | OOXML zip-bomb and decompression limits                                                                           |
| `DOCAI_CONTEXT_CHUNK_CHARS`, `DOCAI_CONTEXT_CHUNK_OVERLAP`, `DOCAI_WHOLE_DOC_MAX_CHARS`                                            | 24000 / 1500 / 60000                                                      | chunking defaults                                                                                                 |
| `DOCAI_CACHE_BACKEND`, `DOCAI_CACHE_LOCATION`, `DOCAI_CACHE_TTL`, `DOCAI_CACHE_MAX_ENTRIES`                                        | LocMem                                                                    | process-local development cache; `/admin/cache/` lets superusers inspect it                                       |
| `DOCAI_THROTTLE_USER`, `DOCAI_THROTTLE_ANON`                                                                                       | 600/min, 60/min                                                           | DRF throttling                                                                                                    |
| `DOCAI_LOG_JSON`, `DOCAI_LOG_LEVEL`, `DOCAI_SLOW_REQUEST_MS`                                                                       | false, INFO, 1000                                                         | Compact local logs; flat JSON in deployment and the rotating file; slow-request warning threshold in milliseconds |
| `DJANGO_SILKY_ENABLED`, `DJANGO_SILKY_MAX_RECORDED_REQUESTS`                                                                       | false, 2000                                                               | Opt-in superuser request/SQL profiler at `/admin/profiler/`; restart after changing it                            |
| `DOCAI_RAW_RESPONSE_RETENTION_DAYS`                                                                                                | 30                                                                        | recorded on raw model-response artifacts                                                                          |
| `CELERY_BROKER_URL`                                                                                                                | `filesystem://` in local settings                                         | broker selected by URL; use a network broker for multiple hosts, with HA provided by that broker's deployment     |
| `CELERY_RESULT_BACKEND`                                                                                                            | disabled                                                                  | leave unset; application status and results live in `Run`/`RunItem`                                               |
| `CELERY_FILESYSTEM_DIR`                                                                                                            | `%LOCALAPPDATA%\DocAI\celery` on Windows; `backend/data/celery` elsewhere | short, single-host message spool                                                                                  |
| `CELERY_WORKER_POOL`                                                                                                               | `solo` on macOS; `threads` on Windows; `prefork` on Linux                   | `threads` \| `solo` \| `prefork`; macOS and Windows reject configured `prefork`                                    |
| `CELERY_WORKER_CONCURRENCY`                                                                                                        | 1 on SQLite; otherwise `DOCAI_MAX_WORKERS`                                | worker processes or threads                                                                                       |
| `CELERY_TASK_TIME_LIMIT`, `CELERY_TASK_SOFT_TIME_LIMIT`                                                                            | 1800 / 1500                                                               | hard and soft worker limits in seconds; soft limits require prefork                                               |
| `CELERY_TASK_MAX_RETRIES`, `CELERY_TASK_MAX_DELIVERIES`                                                                            | 3 / 5                                                                     | bounded transient retries and worker-loss redeliveries per dispatch                                               |

LocMem is appropriate for one development process. To share cache entries across web and worker
processes, install `.[redis]` and set `DOCAI_CACHE_BACKEND=django.core.cache.backends.redis.RedisCache`
plus `DOCAI_CACHE_LOCATION=redis://<host>:6379/1`. The application cache calls and both cache inspectors
then use Redis without code changes.

Dashboard project/dataset/configuration counts are cached for 60 seconds; operational status and next-step guidance
stay live. LLM usage summaries cache aggregates for 5 seconds while processing and 300 seconds after completion,
checking the event count and run revision on every read so worker writes and retries are detected with LocMem too.
Cache fills and catalog invalidation happen after commit. Redis shares catalog invalidation between processes;
with LocMem, catalog counts changed in another process may stay cached for up to 60 seconds.

Superusers have a compact **Operations** section in Django admin:

- `/admin/cache/` inspects the configured Django cache and is always available.
- `/admin/workers/` combines the selected sync, thread, or Celery executor with queued/running `RunItem`
  records. Thread capacity reflects the database limit; Celery mode adds one live worker status query.
- `/admin/celery/` is installed by `.[celery]`. Its overview does not contact the broker; workers, queues,
  and active tasks use Celery's live inspection API and are useful once a worker is running.
- `/admin/redis/` is installed by `.[redis]`. It shows a setup state while LocMem is selected and
  automatically follows `DOCAI_CACHE_LOCATION` when Django's built-in Redis cache is selected. Key editing,
  deletion, and TTL changes are disabled.
- `/admin/errors/` groups current failed `RunItem` records by their sanitized application error code and links
  to the underlying document tasks. It is the durable processing-error view; it does not retain HTTP request
  bodies, stack traces, or secrets.

## Roles (Django groups, created by `seed_defaults`)

| Group             | Can                                                                                               |
| ----------------- | ------------------------------------------------------------------------------------------------- |
| `docai_viewers`   | read everything; sensitive values (raw/reviewed values, evidence, label text) are masked as `•••` |
| `docai_operators` | upload, create configurations, start/cancel/retry runs, inspect LLM token usage, export           |
| `docai_reviewers` | see document content, review fields/classifications, split/merge segments, create labels          |
| `docai_approvers` | approve/retire configurations and templates, promote reviewed values to ground truth              |

Superusers hold every role. RND currently assumes one trusted institutional team: these groups are global and
members can discover every project. `docai/api/permissions.py::can_access_project` is the extension point for
project membership and queryset scoping before use across separate lines of business or need-to-know groups.

## Supported formats

PDF (text-layer PDFs locally; scanned PDFs via DI), JPEG, PNG, TIFF, DOCX, XLSX, XLS, TXT.
Ingestion checks **before any Azure call**: signature-based type detection (extension spoofing is caught),
size, page/sheet limits, duplicate SHA-256 per dataset, corruption, password protection, empty content, and
Excel safety (workbooks with VBA, external links, or embedded objects are refused). Originals are immutable.
DOCX/XLSX containers are also bounded by member count, expanded size, largest member, and compression ratio
before XML or workbook parsing begins.

## Task execution and optional workers

The default `DOCAI_TASK_RUNNER=thread` needs neither Celery nor a broker and runs on Windows,
macOS, and Linux. HTTP run mutations hand work to one bounded process-local coordinator and return `202`; the
coordinator executes one run at a time and, on a server database, uses up to `DOCAI_MAX_WORKERS` document threads.
SQLite processes documents sequentially. `sync` is useful for deterministic direct service calls and tests, while
HTTP work still leaves the request through the coordinator. Both local runners are best-effort because their queue
does not survive a web-process restart. All runners use the same processing services as Celery.

Install the worker dependencies only when you need a separate process:

```bash
uv sync --extra celery
```

The Celery extra also installs its superuser-only admin panel. The Redis extra similarly installs the Redis
panel while leaving it unconfigured until the Redis cache backend is selected.

For single-machine development, set `DOCAI_TASK_RUNNER=celery` and start the worker. Local settings
default to a filesystem broker with no result backend. Windows stores its spool under
`%LOCALAPPDATA%\DocAI\celery`; macOS and Linux use `backend/data/celery`. Redis is not required,
and SQLite limits the configured worker concurrency to one by default.

```bash
DJANGO_SETTINGS_MODULE=config.settings.local celery -A config worker -Q docai --loglevel=INFO
```

macOS selects `solo` to avoid native Objective-C crashes after `fork()`. Replace any old explicit
`CELERY_WORKER_POOL=prefork` in your local `.env` with `solo`, then restart the worker.
Linux selects `prefork`. Windows selects `threads`; set `CELERY_WORKER_POOL=solo` when sequential execution is
more useful for debugging. Celery itself does not officially support Windows, so the broker-free `thread`
runner is the supported default there. Broker directories use native backslashes; the result directory is
not needed. Startup rejects a configured spool whose expected message paths reach
the legacy 260-character Windows boundary; use `CELERY_FILESYSTEM_DIR=C:\docai-celery` in that case.

For the initial single-host Linux deployment, `filesystem://` can use a persistent local spool and `prefork`.
Move to Redis or RabbitMQ before adding worker hosts or requiring broker HA, heartbeats, message TTL, or priority.
Redis remains an environment-only broker change after installing the separate `redis` extra:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=redis://redis.example.internal:6379/0
CELERY_WORKER_POOL=prefork
CELERY_WORKER_CONCURRENCY=4
```

Tasks carry UUIDs rather than model instances, claim each item by Celery task id, retry only failures marked
retryable, and stop repeated worker-loss deliveries at a configured bound. Each terminal task attempts an
idempotent database finalization; no chord or Celery result backend is required.

If a broker or local coordinator rejects a dispatch, the run records `dispatch_failed`. Restoring the runtime and
retrying the original headless request with the same idempotency key schedules that same run. After an ungraceful
web or worker stop, `manage.py recover_stalled_runs` makes sufficiently old unfinished items visible as retryable
failures; it never guesses that recently accepted work is dead.

See the [Celery operations runbook](backend/CELERY.md) for Windows/Linux development, initial one-host Linux
production, filesystem and Redis examples, worker recovery, and commands for each required process.

## Deployment notes

The institution supplies the web server, static host, reverse proxy, and worker service. The application contracts are:

- WSGI target `config.wsgi:application` with `DJANGO_SETTINGS_MODULE=config.settings.production`.
- Release step `python manage.py migrate` followed by `python manage.py collectstatic --noinput`.
- Linux worker `celery -A config worker -Q docai --pool=prefork --concurrency=<approved value>` when Celery is selected.
- Static SPA from `frontend/dist`, with unknown frontend routes sent to `index.html` and `/api`, `/admin`, `/health`,
  and `/static` routed to Django.
- Dependency-free liveness at `/health/live/` and database/cache/storage readiness at `/health/ready/`.

- **Settings**: WSGI and a directly invoked Celery app default to `config.settings.production`, which fails
  closed unless `DOCAI_ENVIRONMENT` is `rnd`, `uat`, `qa`, or `prod` and `DJANGO_SECRET_KEY`, explicit
  `DJANGO_ALLOWED_HOSTS`, and `DATABASE_URL` are set. It forces
  debug off, secure cookies, HTTPS redirects, HSTS, private upload permissions, session-only API auth, and
  authenticated API documentation. If TLS ends at a trusted reverse proxy, set
  `DJANGO_TRUST_X_FORWARDED_PROTO=true` only after the proxy strips incoming `X-Forwarded-Proto` values.
  Run `.venv/bin/python manage.py check --deploy --settings=config.settings.production` before release.
  Copy-ready, secret-free templates for Local, RND, UAT, QA, and Production are documented in
  [`backend/env/`](backend/env/README.md). All deployed stages use the same production settings module;
  their databases, hosts, Azure endpoints, storage paths, and credentials come from deployment configuration.
- **Database**: Oracle via `DATABASE_URL`; install the driver with `uv sync --extra oracle`
  (add `--extra celery` on worker hosts). All indexes/constraints are explicitly named (≤ 26 chars);
  `db_comment` / `db_table_comment` are applied by the deployment database.
- **Storage**: originals and artifacts go through Django's storage API. Moving to Azure Blob keeps application
  services unchanged, but the deployment must add an approved storage backend package and configure Django's
  `STORAGES`; the repository does not currently include `django-storages`. Local paths are Windows-safe and short.
- **Static assets**: `npm run build` → serve `frontend/dist` using the routing and cache contract in
  [`frontend/DEPLOYMENT.md`](frontend/DEPLOYMENT.md), proxying `/api`, `/admin`, and `/health` to Django. Run
  `collectstatic` for the admin and self-hosted Swagger UI assets. CORS/CSRF origins:
  `DOCAI_CORS_ORIGINS`, `DOCAI_CSRF_TRUSTED`. Set `DOCAI_FRONTEND_URL` to the public frontend root so the
  admin's **View site** link follows each environment; `/` is suitable for same-origin deployments.
- **Request limits**: enforce the upload body limit at the reverse proxy or application gateway as well as in
  Django. The application validates each file after multipart parsing; the edge limit protects web-worker memory
  and bandwidth before a request reaches Django.
- **Shared cache**: configure Redis or another shared Django cache when running multiple web processes. LocMem
  throttles login/API traffic independently in each process and is intended for local or single-process use.
- **Logging**: local request lines show method, path, status, duration, user, and request ID. `DOCAI_LOG_JSON=true`
  emits flat structured records; every record carries the environment and request/run correlation ID. Successful health,
  static, favicon, and admin translation requests log at DEBUG. Responses return the full ID in `X-Request-ID`. Secrets
  and PII patterns are redacted before writing. Django, Celery, and Python warnings use the same sinks. Workers show
  processing milestones with task/run/item correlation; routine Celery/SDK chatter requires DEBUG. See
  [worker logs](backend/CELERY.md#worker-logs) for the format and controls.

### RND handoff and promotion gates

RND may use the current global DocAI groups for one trusted team. Before deployment, validate the Oracle URL and
migrations, configure shared storage, choose the task runner and broker, provide Azure credentials through the
institutional secret store, build the frontend, and run the readiness probe plus one live DI/LLM smoke workflow.
HTTP Basic authentication is disabled unless `DOCAI_ENABLE_BASIC_AUTH=true`; when enabled for an RND integration
client it must be behind HTTPS. Browser users continue to use Django sessions.

Before broader UAT or production use, add Entra/OIDC login, enforce project membership in permissions and queryset
scoping, use a network broker and shared cache for multiple processes, define backup and artifact-retention jobs,
complete the staged HSTS rollout, connect logs/health to institutional monitoring, and automate credentialed Azure
smoke tests in the protected deployment pipeline.

## Troubleshooting

| Symptom                               | Cause / fix                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `AZURE_AUTH_FAILED`                   | `az login` expired / wrong tenant, or the managed identity lacks the RBAC roles above                  |
| `LAYOUT_ADAPTER_UNSUPPORTED`          | image/DOCX/scanned input with the local `pypdf` adapter — set `DOCAI_LAYOUT_ADAPTER=azure_di`          |
| `INVALID_MODEL_OUTPUT`                | the model returned something the Pydantic schema rejected; the item is routed to review, never coerced |
| `database is locked` (SQLite)         | use `DOCAI_TASK_RUNNER=sync` or move to Oracle for parallel runs                                       |
| Uploads rejected as `UNSAFE_WORKBOOK` | the workbook contains macros/external links/embedded objects — by design                               |
| Metrics show `out_of_schema_labels`   | ground truth exists for fields this workflow does not extract; reported, not graded                    |
