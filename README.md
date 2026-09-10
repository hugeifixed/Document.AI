# DocAI Platform

Enterprise document AI platform for **unbundling, classification, extraction, labeling, review, and evaluation**
of banking documents. Django 5.2 reusable sub-application (`backend/docai`) + React 19 / Vite / Tailwind 4 / daisyUI 5
frontend (`frontend/`).

* OCR / layout: **Azure AI Document Intelligence** (prebuilt-layout) — the only OCR engine.
* PDF manipulation: **pypdf** only. Excel: openpyxl / xlrd (never evaluates macros or formulas).
* LLM: Azure-hosted GPT through **LangChain + Pydantic structured output**, authenticated with
  **DefaultAzureCredential** (`az login` locally, managed identity deployed). No API keys anywhere.
* Runs locally with **no Azure access at all**: the `pypdf` layout adapter reads text-layer PDFs and the
  deterministic `mock` LLM adapter satisfies the same Pydantic schemas a real model must — the full
  pipeline, metrics, review, labeling and exports all work offline on synthetic documents.

See `ARCHITECTURE.md` for the design decisions and `KNOWN_LIMITATIONS.md` for what is not (yet) real.

---

## Quickstart (local, keyless)

Prerequisites: Python 3.12+, `uv`, Node 20+.

```bash
# backend
cd backend
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"     # Windows: .venv\Scripts\python
cp .env.example .env                                                    # defaults are already keyless
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_defaults --admin-password admin123      # groups, prompts, sample project + 4 workflows
.venv/bin/python manage.py make_synthetic_data --build-layouts          # 18 synthetic docs + 113 ground-truth labels
.venv/bin/python manage.py run_sample                                   # unbundle→classify→extract→evaluate→export
.venv/bin/python manage.py runserver 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev                               # http://localhost:5173 (proxies /api to :8000)
```

Open `http://localhost:5173/` to reach the central sign-in page (seeded account: admin / admin123).
The frontend and Django admin share a Django session. After sign-in, you return to the page you requested;
use **Log out** in the frontend header to end the session. Expired sessions return to sign-in automatically.
Pick the **Sample banking documents** project and **synthetic-dev** dataset in the sidebar.

API docs: `http://localhost:8000/api/docs/` (OpenAPI 3.2). Health: `http://localhost:8000/health/`.

Expected output of `run_sample` with the mock adapter (synthetic dev set):

```
status=succeeded processed=18 failed=0
extraction: acc=0.9577 P=1.0 R=0.9577 F1=0.9784 ...   # per-field taxonomy table follows
classification: acc=0.9333 macroF1=0.8333             # the one miss is the intentionally unconfigured invoice → other
segmentation: boundaryF1=1.0 pageAcc=1.0 exact=1.0 docs=2
```

Backend quality: `cd backend && .venv/bin/ruff check . && .venv/bin/python -m pytest`.
Frontend quality: `cd frontend && npm test && npm run build`.

Install the repository hook once with `uv run --project backend --no-sync pre-commit install`.
It runs Ruff (including the current complexity ceiling) and the backend test suite with branch
coverage whenever staged Python or `pyproject.toml` files change. Run the same gate on demand with
`uv run --project backend --no-sync pre-commit run --all-files`. The coverage floor is 75%; the hook
writes `backend/coverage.xml` for the institutional Sonar scan. Sonar remains the authoritative CI
quality gate, so no server URL or token is required for a local commit.

---

## Using real Azure services

1. **Identity.** Locally run `az login` (or `az login --tenant <id>`). Deployed, assign a managed identity.
   Grant it **Cognitive Services User** on the Document Intelligence resource and
   **Cognitive Services OpenAI User** on the Azure OpenAI resource. Nothing else is needed — no keys.
2. **Endpoints** (in `.env`):
   ```
   DOCAI_LAYOUT_ADAPTER=azure_di
   DOCAI_LLM_ADAPTER=azure_openai
   AZURE_DI_ENDPOINT=https://<your-di>.cognitiveservices.azure.com/
   AZURE_DI_API_VERSION=2024-11-30
   AZURE_OPENAI_ENDPOINT=https://<your-aoai>.openai.azure.com/
   AZURE_OPENAI_API_VERSION=2024-10-21
   AZURE_OPENAI_DEPLOYMENT=gpt-4o
   ```
3. **Model swap** = change the deployment name in a `ModelConfiguration` / workflow `model.deployment`
   (or the env default). Workflow logic never changes; every run records the deployment it used.
4. **Timeouts / retries**: `AZURE_TIMEOUT_S`, `AZURE_MAX_RETRIES`. Throttling (429) and timeouts retry with
   backoff; auth failures do not and surface as `AZURE_AUTH_FAILED` with a plain-language message.

Documents that *require* Azure DI: images (JPEG/PNG/TIFF), DOCX, and image-only (scanned) PDFs.
With the local `pypdf` adapter those are rejected with `LAYOUT_ADAPTER_UNSUPPORTED` rather than silently
producing empty results.

---

## Configuration reference (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | dev values | production requires a unique 50+ character secret and explicit hosts; production always forces debug off |
| `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_TRUST_X_FORWARDED_PROTO` | true / false in production | HTTPS redirect; trust the forwarded-proto header only behind a proxy that strips client-supplied copies |
| `DJANGO_SECURE_HSTS_SECONDS`, `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_SECURE_HSTS_PRELOAD` | 3600 / false / false in production | staged HSTS controls |
| `DOCAI_ENABLE_BASIC_AUTH` | false in production | opt in to HTTP Basic authentication; use only over HTTPS |
| `DATABASE_URL` | `sqlite:///data/docai.sqlite3` | any `dj-database-url` URL: Oracle `oracle://…`, Postgres `postgres://…` |
| `DOCAI_DATA_DIR` | `backend/data` | media (originals, artifacts), logs, exports |
| `DOCAI_LAYOUT_ADAPTER` | `pypdf` | `azure_di` \| `pypdf` \| `fixture` |
| `DOCAI_LLM_ADAPTER` | `mock` | `azure_openai` \| `mock` (a `mock` environment never reaches Azure, even if a workflow says `azure_openai`) |
| `DOCAI_TASK_RUNNER` | `thread` | `sync` \| `thread` \| `celery` (thread parallelism is 1 on SQLite — single-writer DB) |
| `DOCAI_MAX_WORKERS` | 4 | thread runner pool |
| `DOCAI_MAX_UPLOAD_MB`, `DOCAI_MAX_PAGES`, `DOCAI_MAX_SHEETS`, `DOCAI_MAX_BATCH_FILES` | 100 / 500 / 50 / 500 | ingestion limits |
| `DOCAI_MAX_ARCHIVE_MEMBERS`, `DOCAI_MAX_ARCHIVE_MEMBER_MB`, `DOCAI_MAX_ARCHIVE_EXPANDED_MB`, `DOCAI_MAX_ARCHIVE_COMPRESSION_RATIO` | 2000 / 64 / 256 / 100 | OOXML zip-bomb and decompression limits |
| `DOCAI_CONTEXT_CHUNK_CHARS`, `DOCAI_CONTEXT_CHUNK_OVERLAP`, `DOCAI_WHOLE_DOC_MAX_CHARS` | 24000 / 1500 / 60000 | chunking defaults |
| `DOCAI_CACHE_BACKEND`, `DOCAI_CACHE_LOCATION`, `DOCAI_CACHE_TTL`, `DOCAI_CACHE_MAX_ENTRIES` | LocMem | swap to Redis by settings alone; `/admin/cache/` inspects it |
| `DOCAI_THROTTLE_USER`, `DOCAI_THROTTLE_ANON` | 600/min, 60/min | DRF throttling |
| `DOCAI_LOG_JSON`, `DOCAI_LOG_LEVEL`, `DOCAI_SLOW_REQUEST_MS` | false, INFO, 1000 | Compact local logs; flat JSON in deployment and the rotating file; slow-request warning threshold in milliseconds |
| `DOCAI_RAW_RESPONSE_RETENTION_DAYS` | 30 | recorded on raw model-response artifacts |
| `CELERY_BROKER_URL` | `filesystem://` in local settings | broker selected by URL; use a network broker for multiple hosts, with HA provided by that broker's deployment |
| `CELERY_RESULT_BACKEND` | disabled | leave unset; application status and results live in `Run`/`RunItem` |
| `CELERY_FILESYSTEM_DIR` | `%LOCALAPPDATA%\DocAI\celery` on Windows; `backend/data/celery` elsewhere | short, single-host message spool |
| `CELERY_WORKER_POOL` | `threads` on Windows; `prefork` on macOS/Linux | `threads` \| `solo` \| `prefork`; Windows rejects `prefork` |
| `CELERY_WORKER_CONCURRENCY` | 1 on SQLite; otherwise `DOCAI_MAX_WORKERS` | worker processes or threads |
| `CELERY_TASK_TIME_LIMIT`, `CELERY_TASK_SOFT_TIME_LIMIT` | 1800 / 1500 | hard and soft worker limits in seconds; soft limits require prefork |
| `CELERY_TASK_MAX_RETRIES`, `CELERY_TASK_MAX_DELIVERIES` | 3 / 5 | bounded transient retries and worker-loss redeliveries per dispatch |

## Roles (Django groups, created by `seed_defaults`)

| Group | Can |
|---|---|
| `docai_viewers` | read everything; sensitive values (raw/reviewed values, evidence, label text) are masked as `•••` |
| `docai_operators` | upload, create configurations, start/cancel/retry runs, export |
| `docai_reviewers` | see document content, review fields/classifications, split/merge segments, create labels |
| `docai_approvers` | approve/retire configurations and templates, promote reviewed values to ground truth |

Superusers hold every role. Per-project membership is an extension point (`docai/api/permissions.py::can_access_project`).

## Supported formats

PDF (text-layer PDFs locally; scanned PDFs via DI), JPEG, PNG, TIFF, DOCX, XLSX, XLS, TXT.
Ingestion checks **before any Azure call**: signature-based type detection (extension spoofing is caught),
size, page/sheet limits, duplicate SHA-256 per dataset, corruption, password protection, empty content, and
Excel safety (workbooks with VBA, external links, or embedded objects are refused). Originals are immutable.
DOCX/XLSX containers are also bounded by member count, expanded size, largest member, and compression ratio
before XML or workbook parsing begins.

## Task execution and optional workers

The default `DOCAI_TASK_RUNNER=thread` needs neither Celery nor a broker and runs on Windows,
macOS, and Linux. `sync` is useful for debugging. Both use the same processing services as Celery.

Install the worker dependencies only when you need a separate process:

```bash
uv pip install -e ".[celery]"
```

For single-machine development, set `DOCAI_TASK_RUNNER=celery` and start the worker. Local settings
default to a filesystem broker with no result backend. Windows stores its spool under
`%LOCALAPPDATA%\DocAI\celery`; macOS and Linux use `backend/data/celery`. Redis is not required,
and SQLite limits the configured worker concurrency to one by default.

```bash
DJANGO_SETTINGS_MODULE=config.settings.local celery -A config worker -Q docai --loglevel=INFO
```

Windows selects `threads` automatically; set `CELERY_WORKER_POOL=solo` when sequential execution is
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

See the [Celery operations runbook](backend/CELERY.md) for Windows/Linux development, initial one-host Linux
production, filesystem and Redis examples, worker recovery, and commands for each required process.

## Deployment notes

* **Settings**: WSGI and a directly invoked Celery app default to `config.settings.production`, which fails
  closed unless `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS`, and `DATABASE_URL` are set. It forces
  debug off, secure cookies, HTTPS redirects, HSTS, private upload permissions, session-only API auth, and
  authenticated API documentation. If TLS ends at a trusted reverse proxy, set
  `DJANGO_TRUST_X_FORWARDED_PROTO=true` only after the proxy strips incoming `X-Forwarded-Proto` values.
  Run `.venv/bin/python manage.py check --deploy --settings=config.settings.production` before release.
* **Database**: Oracle or PostgreSQL via `DATABASE_URL`. All indexes/constraints are explicitly named (≤ 26 chars);
  `db_comment` / `db_table_comment` are applied on those backends.
* **Storage**: originals and artifacts go through Django's storage API. Point `STORAGES["default"]` at Azure Blob
  (`django-storages`) with no code change; paths are Windows-safe and short.
* **Static assets**: `npm run build` → serve `frontend/dist` from your web server or CDN, proxying `/api`, `/admin`,
  `/health` to Django. Run `collectstatic` for the admin and self-hosted Swagger UI assets. CORS/CSRF origins:
  `DOCAI_CORS_ORIGINS`, `DOCAI_CSRF_TRUSTED`.
* **Request limits**: enforce the upload body limit at the reverse proxy or application gateway as well as in
  Django. The application validates each file after multipart parsing; the edge limit protects web-worker memory
  and bandwidth before a request reaches Django.
* **Shared cache**: configure Redis or another shared Django cache when running multiple web processes. LocMem
  throttles login/API traffic independently in each process and is intended for local or single-process use.
* **Logging**: local request lines show method, path, status, duration, user, and request ID. `DOCAI_LOG_JSON=true`
  emits flat structured records; every record carries the request/run correlation ID. Successful health, static, favicon,
  and admin translation requests log at DEBUG. Responses return the full ID in `X-Request-ID`. Secrets and PII patterns
  are redacted before writing. Django logs and Python warnings use the same sinks and request context.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `AZURE_AUTH_FAILED` | `az login` expired / wrong tenant, or the managed identity lacks the RBAC roles above |
| `LAYOUT_ADAPTER_UNSUPPORTED` | image/DOCX/scanned input with the local `pypdf` adapter — set `DOCAI_LAYOUT_ADAPTER=azure_di` |
| `INVALID_MODEL_OUTPUT` | the model returned something the Pydantic schema rejected; the item is routed to review, never coerced |
| `database is locked` (SQLite) | use `DOCAI_TASK_RUNNER=sync` or move to Postgres/Oracle for parallel runs |
| Uploads rejected as `UNSAFE_WORKBOOK` | the workbook contains macros/external links/embedded objects — by design |
| Metrics show `out_of_schema_labels` | ground truth exists for fields this workflow does not extract; reported, not graded |
