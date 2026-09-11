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

For local development, copy the template before starting Django:

```bash
cp env/local.env.example .env
```

```powershell
Copy-Item env/local.env.example .env
```

`manage.py` selects local settings by default. Pytest selects test settings in `pyproject.toml` and
does not need an environment file.

`DOCAI_FRONTEND_URL` controls the admin account menu's **View site** destination. Local settings
default it to `http://localhost:5173/`. Deployed stages use `/` for a frontend served from the same
origin; set a full public URL when the frontend is hosted on a separate origin. This keeps host names
in deployment configuration rather than application code.

For a deployed stage, set `DJANGO_SETTINGS_MODULE=config.settings.production` in the process
environment before Python starts. Supply the matching template values through the deployment
platform and its secret store. Django cannot select its settings module from a `.env` file that is
loaded later while importing those settings.

The deployed templates assume Oracle and the initial single-host Linux topology. Install the
`oracle` and `celery` extras with `uv pip install -e ".[celery,oracle]"`. The templates select
Celery's filesystem broker and `prefork` pool. Mount `DOCAI_DATA_DIR` on persistent storage shared
by the web and worker processes, and move to a network broker before using multiple hosts. See
`../CELERY.md` for the worker commands and Redis alternative.

Replace every placeholder before deployment. In particular, the example secret is intentionally too
weak for startup. `config.settings.production` requires a unique secret, explicit hosts, a database
URL, and `DOCAI_ENVIRONMENT=rnd|uat|qa|prod`.

Do not commit populated `.env` files. These templates contain names and placeholders only; managed
identity supplies Azure credentials.
