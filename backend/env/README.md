# Environment templates

The five institutional environments use two Django settings modules. Local development uses
`config.settings.local`; every deployed stage uses the same fail-closed
`config.settings.production` module so security and runtime behavior do not drift between RND,
UAT, QA, and Production.

| Environment | Template | Django settings | Purpose |
|---|---|---|---|
| Local | `local.env.example` | `config.settings.local` | SQLite, local adapters, thread runner with inline SQLite execution |
| RND | `rnd.env.example` | `config.settings.production` | RND infrastructure and Azure endpoints |
| UAT | `uat.env.example` | `config.settings.production` | UAT infrastructure and Azure endpoints |
| QA | `qa.env.example` | `config.settings.production` | QA infrastructure and Azure endpoints |
| Production | `production.env.example` | `config.settings.production` | Production infrastructure and Azure endpoints |
| Automated tests | None | `config.settings.test` | In-memory database, mocks, synchronous execution |

`DOCAI_TASK_RUNNER=sync|thread` does not make HTTP run requests synchronous. Both are accepted by one bounded,
process-local coordinator and return `202`; `sync` controls how that coordinator processes document items. Use
`celery` with a durable network broker when accepted work must survive a web-process restart or span hosts.

For local development, copy the template before starting Django:

```bash
cp env/local.env.example .env
```

```powershell
Copy-Item env/local.env.example .env
```

`manage.py` selects local settings by default. Pytest selects test settings in `pyproject.toml` and
does not need an environment file.

For temporary testing, local settings alone accept `AZURE_DI_API_KEY` and `AZURE_OPENAI_API_KEY`
in the ignored `.env`. Each key takes precedence over identity for its service when populated;
clear it and restart both Django and Celery to return to identity. Other settings modules keep
identity authentication. The DI and LLM keys belong to their respective Azure resources.

## Template organization

All five templates follow the same order: Django/database and browser access; adapter selection;
Azure identity, DI, OpenAI, and request settings; scan enhancement; processing and Celery; upload
limits; cache; throttling; logging; profiling. Deployed stages also include transport security and
persistent storage. Local-only API keys and evidence diagnostics are marked in their own service
or logging sections. Shared settings keep the same names across stages; endpoint, host, database,
and storage values remain specific to each environment.
`DOCAI_BUILD_SHA` is optional deployment metadata shown on the human status page; inject the deployed
commit SHA during release and leave it blank locally when it is not available.

## Azure service principal

Service-principal authentication works in local, RND, UAT, QA, and Production without code changes.
Uncomment the three identity entries in the chosen template and supply their real values through
the deployment secret store (or your ignored local `.env`):

```dotenv
AZURE_TENANT_ID=your-directory-tenant-id
AZURE_CLIENT_ID=your-application-client-id
AZURE_CLIENT_SECRET=your-client-secret-value
```

Use the client secret **value**, not its identifier. `adapters/azure_identity.py` constructs
`DefaultAzureCredential`; the Azure SDK's `EnvironmentCredential` reads these variables directly
from the process environment. Django's base settings load local `.env` entries into that environment
before the credential is created, so separate Django settings for these variables are unnecessary.
See the [Azure Identity documentation](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/identity/azure-identity/README.md).

Supply all three to both Django and Celery processes. The shared identity needs **Cognitive Services
User** on the DI resource and **Cognitive Services OpenAI User** on the LLM resource. Configure each
service's root endpoint, supported API version, and the LLM deployment name as shown in the templates;
the server also needs network access to Microsoft Entra and those endpoints. Clear local API keys to
use identity, and restart Django and any Celery workers after credential changes. The thread runner
only requires restarting Django.

The identity entries are commented out deliberately: do not supply three empty strings when choosing
Azure CLI or managed identity instead. A fully configured service principal takes precedence over
those credentials; invalid credentials are not a reason to fall back to a developer's login.

## Frontend URLs

`DOCAI_FRONTEND_URL` controls the admin account menu's **View site** destination. Local settings
default it to `http://localhost:5173/`. Deployed stages use `/` for a frontend served from the same
origin; set a full public URL when the frontend is hosted on a separate origin. This keeps host names
in deployment configuration rather than application code.

## Deployment and optional services

For a deployed stage, set `DJANGO_SETTINGS_MODULE=config.settings.production` in the process
environment before Python starts. Supply the matching template values through the deployment
platform and its secret store. Django cannot select its settings module from a `.env` file that is
loaded later while importing those settings.

The deployed templates assume Oracle and the initial single-host Linux topology. Install the
`oracle` and `celery` extras with `uv sync --extra celery --extra oracle`. The templates select
Celery's filesystem broker and `prefork` pool. Mount `DOCAI_DATA_DIR` on persistent storage shared
by the web and worker processes, and move to a network broker before using multiple hosts. See
`../CELERY.md` for the worker commands and Redis alternative.

Run `python manage.py cleanup_expired_invocations` on an institutional schedule after the configured 30-day
idempotency window. It removes only expired terminal or pre-run-failed reservations; active runs retain their retry
identity. Run `python manage.py recover_stalled_runs` after an ungraceful local coordinator or worker stop, using the
safety window described in `../CELERY.md`.

Every template defaults `DOCAI_IMAGE_NORMALIZATION_ENABLED=false`. Enabling it requires the
optional `image-normalization` extra and an adaptive workflow. Supply the same gate on web and
worker processes and restart both. See `../IMAGE_NORMALIZATION.md` before enabling RND/QA.

Replace every placeholder before deployment. In particular, the example secret is intentionally too
weak for startup. `config.settings.production` requires a unique secret, explicit hosts, a database
URL, and `DOCAI_ENVIRONMENT=rnd|uat|qa|prod`.

Do not commit populated `.env` files. These templates contain names and placeholders only. Supply
service-principal secrets through the deployment secret store, or use managed identity without a secret.
