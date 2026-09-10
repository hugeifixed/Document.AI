# Celery operations runbook

DocAI uses `DOCAI_TASK_RUNNER=thread` by default. It needs no Celery installation or broker, works on
Windows and Linux, and is the easiest development mode. It executes inside the web request, so select
`DOCAI_TASK_RUNNER=celery` when processing must continue in a separate worker process.

| Mode | Broker service | Result backend | Intended use |
|---|---|---|---|
| `thread` | None | None | Default local development and native Windows fallback |
| Celery with `filesystem://` | None | None | One-machine development or initial one-host Linux deployment |
| Celery with Redis | Redis | None | Multiple hosts, broker HA, and stronger operations |

Run and item state is stored in the application database. Celery publishes one task per `RunItem`; each
terminal task attempts an idempotent database finalization. Chords and Celery result storage are not used.
`CELERY_RESULT_BACKEND` may remain empty even when Redis is the broker.

## Install the worker

Linux or macOS:

```bash
cd backend
uv venv --python 3.12  # first setup only
uv pip install --python .venv/bin/python -e ".[celery]"
```

Windows PowerShell:

```powershell
Set-Location backend
uv venv --python 3.12  # first setup only
uv pip install --python .venv\Scripts\python.exe -e ".[celery]"
```

The `celery` extra does not install the Redis client. Install `.[celery,redis]` only when selecting a Redis
broker.

## Development without Redis

The filesystem transport exchanges JSON messages through a directory shared by Django and one worker on
the same computer. There is no broker service to start.

Linux or macOS `.env`:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
CELERY_RESULT_BACKEND=
CELERY_WORKER_POOL=prefork
CELERY_WORKER_CONCURRENCY=1
```

Start Django and the worker in separate terminals:

```bash
cd backend
.venv/bin/python manage.py check
.venv/bin/python manage.py runserver
```

```bash
cd backend
DJANGO_SETTINGS_MODULE=config.settings.local .venv/bin/celery -A config worker \
  --pool=prefork --concurrency=1 -Q docai --loglevel=INFO
```

The default spool is `backend/data/celery`. SQLite intentionally limits concurrency to one because it is a
single-writer database.

Native Windows `.env`:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
CELERY_RESULT_BACKEND=
CELERY_WORKER_POOL=threads
CELERY_WORKER_CONCURRENCY=1
```

Start Django and the worker in separate PowerShell windows:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py runserver
```

```powershell
Set-Location backend
$env:DJANGO_SETTINGS_MODULE = "config.settings.local"
.\.venv\Scripts\celery.exe -A config worker --pool=threads --concurrency=1 -Q docai --loglevel=INFO
```

Windows defaults to `%LOCALAPPDATA%\DocAI\celery`. Use a shorter absolute spool if the startup check reports
that a generated message path could exceed legacy `MAX_PATH`:

```dotenv
CELERY_FILESYSTEM_DIR=C:\docai-celery
```

Use `--pool=solo` for sequential debugging. Celery does not officially support native Windows, and thread or
solo pools do not enforce soft time limits. The built-in `thread` runner or Celery under WSL2 is the reliable
fallback if a dependency does not behave correctly in a native Windows worker.

## Initial one-host Linux production without Redis

This transitional mode requires Django and the worker on the same host with a persistent local spool for queued
messages. Do not place the spool on NFS and do not run worker nodes on other machines. The filesystem transport has no broker
HA, heartbeats, message TTL, or priority. An abrupt loss of the entire worker process or host may strand the
message it was executing even with late acknowledgement; the database recovery command below detects that state.

Create a service-owned spool:

```bash
sudo install -d -o docai -g docai -m 0750 /var/lib/docai/celery
```

Set the production environment:

```dotenv
DJANGO_SETTINGS_MODULE=config.settings.production
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
CELERY_FILESYSTEM_DIR=/var/lib/docai/celery
CELERY_RESULT_BACKEND=
CELERY_WORKER_POOL=prefork
CELERY_WORKER_CONCURRENCY=4
```

Use concurrency `1` with SQLite. PostgreSQL or Oracle can start at `4` and should be tuned from measured
database, Azure, CPU, and memory capacity.

A minimal systemd service is:

```ini
[Unit]
Description=DocAI Celery worker
After=network.target

[Service]
Type=simple
User=docai
Group=docai
WorkingDirectory=/opt/docai/backend
EnvironmentFile=/etc/docai/backend.env
ExecStart=/opt/docai/backend/.venv/bin/celery -A config worker --pool=prefork --concurrency=4 -Q docai --loglevel=INFO
Restart=on-failure
RestartSec=5
TimeoutStopSec=1800

[Install]
WantedBy=multi-user.target
```

Run `manage.py migrate` and `manage.py check --deploy --settings=config.settings.production` before starting
or restarting the worker. Use a graceful `TERM` stop so an active document can finish within
`TimeoutStopSec`.

After an ungraceful worker or host failure, run:

```bash
DJANGO_SETTINGS_MODULE=config.settings.production .venv/bin/python manage.py recover_stalled_runs
```

It waits until an item has remained `running` or waiting to publish a retry for longer than the greater of the
hard task limit or maximum retry delay, plus five minutes. It marks the item as a retryable `WORKER_LOST` failure
and finalizes the run when no other items remain active. Inspect the cause and use the normal run retry action.
Schedule this command with a systemd timer if unattended recovery visibility is required before Redis or RabbitMQ
is introduced. Run it only after confirming the old worker has stopped when using a pool that cannot enforce the
hard limit.

## Move the broker to Redis later

Install the driver and change environment values; application code and database models stay the same:

```bash
uv pip install --python .venv/bin/python -e ".[celery,redis]"
```

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=redis://redis.example.internal:6379/0
CELERY_RESULT_BACKEND=
CELERY_WORKER_POOL=prefork
CELERY_WORKER_CONCURRENCY=4
CELERY_BROKER_VISIBILITY_TIMEOUT=3600
```

The visibility timeout must exceed the hard task limit. The default is at least 3600 seconds or the hard
limit plus five minutes, whichever is greater. Configure `rediss://` and credentials according to the
deployment's secret and TLS standards.

For local Redis testing with Docker:

```console
docker run -d --name docai-redis -p 127.0.0.1:6379:6379 -v docai-redis-data:/data redis:8-alpine redis-server --appendonly yes
docker exec docai-redis redis-cli PING
```

## Delivery, retry, and completion behavior

Tasks contain string UUIDs, never ORM instances or document bytes. A database claim stores the active Celery
task id and suppresses a concurrent duplicate delivery. Celery retries only failures marked `retryable` by the
domain service, using bounded exponential backoff with jitter. Repeated worker-loss deliveries also have a
separate bound so a document that consistently kills a worker cannot loop forever.

The defaults are three automatic retries, five deliveries per dispatch, a 15-second backoff factor, a
10-minute retry cap, a 25-minute soft limit, and a 30-minute hard limit. A failed item remains visible in the
database and can be retried manually from the existing run endpoint. Prefetch is one so a worker does not
reserve a backlog of long documents, and prefork children recycle after 20 tasks to contain gradual memory
growth.

## Verify and operate

1. Run `manage.py migrate` after deployment.
2. Run `manage.py check` with the same environment used by Django and the worker.
3. Confirm `celery -A config report` shows the intended broker, disabled results, pool, concurrency, and queue.
4. Start a workflow and confirm `RunItem` rows progress through `queued`, `running`, and a terminal state.
5. Use the UI/API progress endpoint and structured logs as the primary operational view.

| Symptom | Resolution |
|---|---|
| Celery is not installed | Install `.[celery]`. |
| Redis driver is missing | Install `.[celery,redis]`. |
| Native Windows worker fails | Use `threads` or `solo`; fall back to the built-in runner or WSL2. |
| SQLite reports `database is locked` | Set worker concurrency to `1`, or move to PostgreSQL/Oracle. |
| Filesystem tasks remain queued | Confirm Django and the worker use the same settings, spool path, OS user, and permissions. |
| Run stage is `dispatch_failed` | Restore the broker and execute the run again; completed items will not be duplicated. |
| Item reaches `WORKER_DELIVERY_LIMIT` | Inspect worker exits or hard timeouts, correct the cause, then manually retry the failed item. |

## Official references

- [Celery workers](https://docs.celeryq.dev/en/stable/userguide/workers.html)
- [Celery concurrency](https://docs.celeryq.dev/en/stable/userguide/concurrency/)
- [Celery task retry and acknowledgement](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Kombu filesystem transport](https://docs.celeryq.dev/projects/kombu/en/stable/reference/kombu.transport.filesystem.html)
