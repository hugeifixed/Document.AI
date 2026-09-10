# Celery development runbook

DocAI uses its in-process thread runner by default. This is the simplest local setup and does not need
Celery or a broker. Choose Celery when you want document processing to run in a separate worker process.

| Configuration | Separate broker server | Result storage | Worker pool |
|---|---|---|---|
| `DOCAI_TASK_RUNNER=thread` | None | None | In-process threads |
| Celery with `filesystem://` | None | Local files | `prefork` on macOS/Linux; `threads` or `solo` on Windows |
| Celery with Redis | Redis | Redis | `prefork` on macOS/Linux; `threads` or `solo` on Windows |

The snippets assume the first shell starts at the repository root and then changes into `backend`.
Django and the Celery worker read the same `.env` file, so restart both processes after changing task
or broker settings.

## Install the optional worker dependencies

On macOS or Linux:

```bash
cd backend
uv venv --python 3.12  # First setup only
uv pip install --python .venv/bin/python -e ".[celery]"
```

On Windows PowerShell:

```powershell
Set-Location backend
uv venv --python 3.12  # First setup only
uv pip install --python .venv\Scripts\python.exe -e ".[celery]"
```

## Option 1: filesystem transport without Redis

This is the smallest Celery setup for development on one computer. The web process and worker exchange
messages through a shared directory. There is no broker service or broker command to start.

### macOS

Set these values in `backend/.env`:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
CELERY_RESULT_BACKEND=
CELERY_WORKER_POOL=prefork
CELERY_WORKER_CONCURRENCY=1
```

An empty `CELERY_RESULT_BACKEND` selects the local filesystem result backend. The default shared directory
is `backend/data/celery`.

Start Django in one terminal:

```bash
cd backend
.venv/bin/python manage.py check
.venv/bin/python manage.py runserver
```

Start the worker in a second terminal:

```bash
cd backend
DJANGO_SETTINGS_MODULE=config.settings.local .venv/bin/celery -A config worker -Q docai,docai.ingest --loglevel=INFO
```

### Windows

Set these values in `backend/.env`:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
CELERY_RESULT_BACKEND=
CELERY_WORKER_POOL=threads
CELERY_WORKER_CONCURRENCY=1
```

The default shared directory is `%LOCALAPPDATA%\DocAI\celery`. If the Windows user-profile path is long,
set a shorter absolute path:

```dotenv
CELERY_FILESYSTEM_DIR=C:\docai-celery
```

Start Django in one PowerShell window:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py runserver
```

Start the worker in a second PowerShell window:

```powershell
Set-Location backend
$env:DJANGO_SETTINGS_MODULE = "config.settings.local"
.\.venv\Scripts\celery.exe -A config worker -Q docai,docai.ingest --loglevel=INFO
```

If a Windows library is incompatible with threads, set `CELERY_WORKER_POOL=solo` and restart the worker.
Solo processes one task at a time. Celery does not officially support Windows, so keep the default
`DOCAI_TASK_RUNNER=thread` when a separate worker is unnecessary.

## Option 2: Redis broker and result backend

Redis is optional. It is useful when a durable broker service is available or when the web process and
workers do not share one filesystem.

### Start Redis with Docker on macOS or Windows

Docker is the most consistent cross-platform option. On Windows, use Docker Desktop with Linux containers.

```console
docker run -d --name docai-redis -p 127.0.0.1:6379:6379 -v docai-redis-data:/data redis:8-alpine redis-server --appendonly yes
docker exec docai-redis redis-cli PING
```

The health command should print `PONG`. Use these commands on later development sessions:

```console
docker start docai-redis
docker stop docai-redis
```

### Start Redis natively on macOS

```bash
brew install redis
brew services start redis
redis-cli PING
```

### Point DocAI at Redis

Set the shared task configuration in `backend/.env`:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
CELERY_WORKER_CONCURRENCY=1
```

Then choose the pool for the operating system:

```dotenv
# macOS/Linux
CELERY_WORKER_POOL=prefork
```

```dotenv
# Windows
CELERY_WORKER_POOL=threads
```

Start Django and the Celery worker with the same two-terminal commands from Option 1. Redis is the only
additional server process. Keep concurrency at one while using SQLite; PostgreSQL deployments can raise it
after measuring their workload.

## Switch back to the built-in runner

Set this value, then restart Django. The Celery worker and Redis can be stopped.

```dotenv
DOCAI_TASK_RUNNER=thread
```

Broker settings may remain in `.env`; the built-in runner does not use them.

## Check the setup

1. Run `manage.py check` before starting the server.
2. Confirm that the worker startup banner shows the expected transport, result backend, pool, and the
   `docai` and `docai.ingest` queues.
3. Start a workflow in the UI and confirm that the worker receives its tasks and the run reaches a final
   status after all documents finish.

| Symptom | Resolution |
|---|---|
| Celery is not installed | Install the project with the `celery` extra shown above. |
| Windows reports a prefork or child-process error | Use `CELERY_WORKER_POOL=threads` or `solo`. |
| SQLite reports that the database is locked | Set `CELERY_WORKER_CONCURRENCY=1`, or use PostgreSQL for concurrent workers. |
| Redis reports connection refused | Start Redis and verify `redis-cli PING` or the Docker health command returns `PONG`. |
| Filesystem tasks remain queued | Confirm Django and the worker use the same `.env` and `CELERY_FILESYSTEM_DIR`, then restart both. |

The filesystem transport is intended for a single development computer. Use Redis or another supported
network broker when workers run on separate hosts; Linux production workers should use `prefork`.

## Related official documentation

- [Celery workers](https://docs.celeryq.dev/en/stable/userguide/workers.html)
- [Celery concurrency options](https://docs.celeryq.dev/en/stable/userguide/concurrency/)
- [Install Redis with Docker](https://redis.io/docs/latest/operate/oss_and_stack/install/install-stack/docker/)
- [Install Redis with Homebrew on macOS](https://redis.io/docs/latest/operate/oss_and_stack/install/install-stack/homebrew/)
