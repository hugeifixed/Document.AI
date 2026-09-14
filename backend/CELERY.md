# Celery operations runbook

DocAI uses `DOCAI_TASK_RUNNER=thread` by default. It needs no Celery installation or broker, works on
Windows, macOS, and Linux, and is the easiest development mode. It executes inside the web request, so select
`DOCAI_TASK_RUNNER=celery` when processing must continue in a separate worker process.

| Mode | Broker service | Result backend | Intended use |
|---|---|---|---|
| `thread` | None | None | Default local development and native Windows fallback |
| Celery with `filesystem://` | None | None | One-machine development or initial one-host Linux deployment |
| Celery with Redis | Redis | None | Multiple worker hosts; HA depends on how Redis is deployed |

Run and item state is stored in the application database. Celery publishes one task per `RunItem`; each
terminal task attempts an idempotent database finalization. Chords and Celery result storage are not used.
`CELERY_RESULT_BACKEND` may remain empty even when Redis is the broker.

Optional [scan enhancement](IMAGE_NORMALIZATION.md) runs in this same per-document task before DI;
it adds no queue or broker. Install `.[celery,image-normalization]` only when enabling that capability.
PDFium work is serialized per process in thread/solo configurations; Linux prefork provides rendering
parallelism across processes. Change the gate on both web and worker processes and restart both.
Historical derived sources remain readable with the gate off.

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

Celery and Kombu do not declare `pywin32` themselves, although Kombu's filesystem transport imports its
Win32 locking modules on native Windows. This project's `celery` extra therefore includes `pywin32` behind a
Windows-only dependency marker. It does not install the Redis client. Install `.[celery,redis]` only when
selecting a Redis broker.

## Development without Redis

The filesystem transport exchanges JSON messages through a directory shared by Django and one worker on
the same computer. There is no broker service to start.

macOS `.env`:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
CELERY_WORKER_POOL=solo
CELERY_WORKER_CONCURRENCY=1
```

For Linux development, use `CELERY_WORKER_POOL=prefork`. Leaving the pool unset selects `solo`
on macOS, `threads` on Windows, and `prefork` on Linux. An existing explicit `.env` value overrides
these defaults.

macOS native libraries can abort a forked child with an Objective-C `initialize` / `fork()` error.
Use `solo` for this application's macOS worker; it processes one document at a time in the main
thread of a separate worker process. `threads` is also available. Do not disable macOS fork-safety
checks or pass `--pool=prefork` on macOS. Django's startup checks reject a configured macOS prefork pool.
Neither `solo` nor `threads` enforces Celery soft or hard task limits; SDK timeouts still apply.

Start Django and the worker in separate terminals:

```bash
cd backend
.venv/bin/python manage.py check
.venv/bin/python manage.py runserver
```

```bash
cd backend
DJANGO_SETTINGS_MODULE=config.settings.local .venv/bin/celery -A config worker \
  -Q docai --loglevel=INFO
```

The default spool is `backend/data/celery`. SQLite intentionally limits concurrency to one because it is a
single-writer database.

Native Windows `.env`:

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
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
.\.venv\Scripts\celery.exe -A config worker -Q docai --loglevel=INFO
```

Windows defaults to `%LOCALAPPDATA%\DocAI\celery`. Use a shorter absolute spool if the startup check reports
that a generated message path could exceed legacy `MAX_PATH`:

```dotenv
CELERY_FILESYSTEM_DIR=C:\docai-celery
```

Set `CELERY_WORKER_POOL=solo` for sequential debugging. Celery does not officially support native Windows,
and thread or solo pools do not enforce soft time limits. The built-in `thread` runner or Celery under WSL2
is the reliable fallback if a dependency does not behave correctly in a native Windows worker.

## Initial one-host Linux production without Redis

This transitional mode requires Django and the worker on the same host with a persistent local spool for queued
messages. Do not place the spool on NFS and do not run worker nodes on other machines. The filesystem transport
has no broker HA, heartbeats, message TTL, or priority. An abrupt loss of the entire worker process or host may
strand the message it was executing even with late acknowledgement; the database recovery command below detects
that state.

Create a service-owned spool:

```bash
sudo install -d -o docai -g docai -m 0750 /var/lib/docai/celery
```

Set the production environment:

```dotenv
DJANGO_SETTINGS_MODULE=config.settings.production
DOCAI_ENVIRONMENT=prod
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=filesystem://
CELERY_FILESYSTEM_DIR=/var/lib/docai/celery
CELERY_WORKER_POOL=prefork
CELERY_WORKER_CONCURRENCY=4
```

Use concurrency `1` with SQLite. Oracle can start at `4` and should be tuned from measured
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
ExecStart=/opt/docai/backend/.venv/bin/celery -A config worker -Q docai --loglevel=INFO
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
DOCAI_ENVIRONMENT=prod DJANGO_SETTINGS_MODULE=config.settings.production \
  .venv/bin/python manage.py recover_stalled_runs
```

It waits until an item has remained `running` or waiting to publish a retry for longer than the greater of the
hard task limit or maximum retry delay, plus five minutes. It marks the item as a retryable `WORKER_LOST` failure
and finalizes the run when no other items remain active. Inspect the cause and use the normal run retry action.
Run it only after confirming the old worker has stopped when using a pool that cannot enforce the hard limit.

## Move the broker to Redis later

Install the driver and change environment values; application code and database models stay the same.
The example below is for Linux; keep `solo` on macOS or `threads` on Windows when testing Redis locally:

```bash
uv pip install --python .venv/bin/python -e ".[celery,redis]"
```

```dotenv
DOCAI_TASK_RUNNER=celery
CELERY_BROKER_URL=redis://redis.example.internal:6379/0
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
task id and suppresses a concurrent duplicate delivery. The task uses late acknowledgement and worker-loss
rejection. Celery retries only failures explicitly marked `retryable` by the domain service; unexpected internal
errors fail once. Retryable failures use bounded exponential backoff with jitter. Repeated worker-loss deliveries
have a separate bound so a document that consistently kills a worker cannot loop forever.

The defaults are three automatic retries, five deliveries per dispatch, a 15-second backoff factor, a
10-minute retry cap, a 25-minute soft limit, and a 30-minute hard limit. A failed item remains visible in the
database and can be retried manually from the existing run endpoint. Prefetch is one so a worker does not
reserve a backlog of long documents.

## Worker logs

Celery uses the existing Loguru configuration through its `setup_logging` signal. Local workers show
one compact format for application milestones, Celery warnings, and Python warnings:

```text
10:24:01 I process_run_item[a62f11e4] | Processing started | run=bf413abc item=ced612ac doc=dec78abc attempt=1 req=ab12cd34
10:24:02 I process_run_item[a62f11e4] | OCR started | ... service=azure_di
10:24:05 I process_run_item[a62f11e4] | OCR completed | ... pages=8 chars=19342 duration_ms=3100
10:24:05 I process_run_item[a62f11e4] | Chunking completed | ... chunks=3 strategy=context_length
10:24:05 I process_run_item[a62f11e4] | LLM extraction started | ... service=azure_openai model=your-deployment
10:24:09 I process_run_item[a62f11e4] | Processing completed | ... duration_ms=7310 fields=12 warnings=0
```

The middle lines abbreviate repeated correlation fields with `...` for readability here. Task, run, item,
and document IDs are shortened only in the worker console. JSON output and the rotating
`DOCAI_DATA_DIR/logs/docai.log` file retain full IDs, the request ID, environment, and structured event names.
`config.settings.production` continues to default to JSON; `DOCAI_LOG_JSON=true` also enables it locally.
Colour follows terminal support and is disabled for files/pipes. `--logfile` is supported by the same logger.

- `pypdf` reports **Layout reading**, because it reads text layers; **OCR** is reserved for an OCR-capable adapter.
- **Saved layout reused** means a compatible existing artifact was used; OCR and scan preparation did not rerun.
- Adaptive input preparation reports start and outcome, including adjusted/skipped page counts and fallback warnings.
- LLM start appears once per stage per document attempt. Individual call completion and subsequent call starts are
  DEBUG records. Mock calls identify `service=mock`. Rule-only classification does not claim to have called an LLM.
- Failure lines include the failed stage, machine-readable error code, elapsed time, and whether a retry is pending.
  Retry requests include the backoff delay. Completion includes result and warning counts, never extracted values.
- Azure failures also include `exception_type`, `upstream_status`, and `provider_request_id` when available.
  `attempt` counts document processing attempts; `provider_attempt` counts calls within one SDK retry loop.
  `provider_call_failed` and `processing_failed` distinguish the provider failure from its document outcome.
  Unexpected processing failures show their exception type and code location at ERROR level; JSON includes
  call locations without exception payloads or locals. API access logs include `error_code` and exception type.
- `AZURE_RESPONSE_INVALID` means a provider response could not be read in the expected format, including
  exceptions carrying HTTP 200. It does not mean an Azure outage. `LLM_OUTPUT_TRUNCATED` means the model's
  output limit was reached; `LLM_CONTENT_FILTERED` means a provider filter blocked its response. These do not
  automatically retry unchanged requests. Operators should inspect diagnostics or adjust the workflow first.
  If an SDK failure exposes token usage, it is recorded once as `invalid_output` in the existing usage events;
  missing usage remains unavailable. Response bodies and prompts are never added to diagnostic logs.
- Routine Celery `received`/`succeeded`/`retry` messages and SDK HTTP chatter are hidden at INFO. Warnings, worker
  crashes, and errors stay visible. Use `--loglevel=DEBUG` temporarily for transport and individual-call diagnostics.

No new package or broker is needed. The domain milestones also work with the thread/synchronous runners.
Do not add `CELERY_WORKER_LOG_FORMAT`/`CELERY_WORKER_TASK_LOG_FORMAT` expecting them to style application logs:
Celery's built-in formatters are bypassed so all records use the same redaction and JSON handling.
Restart the worker after changing logging code or settings; Django's development autoreloader does not reload it.

## Verify and operate

The run page reads durable processing milestones from the application database for every runner, including
`solo` and the filesystem broker. It shows the current operation, measured scan/chunk counters when available,
and elapsed time during provider calls. This does not depend on Celery events, remote inspection, a results
backend, Redis, or an extra heartbeat task. Live status counts cover the entire run; item filters and pagination
only change the documents being displayed.

After deploying progress changes, apply migrations and restart Django and all workers. Older runs have no
granular snapshot and continue to show their existing lifecycle status; no historical backfill is needed.
An **Updates interrupted** message means the browser has not refreshed successfully for 15 seconds. Use its
refresh action or check the API connection. **No new milestone** after two minutes describes the last recorded
operation; an OCR/LLM call can still be waiting. Neither message alone proves the worker is stuck or healthy.
Queued documents say **Waiting for a worker**, which can also mean the existing workers are busy.

1. Run `manage.py migrate` after deployment.
2. Run `manage.py check` with the same environment used by Django and the worker.
3. Confirm `celery -A config report` shows the intended broker, disabled results, pool, concurrency, and queue.
4. Start a workflow and confirm `RunItem` rows progress through `queued`, `running`, and a terminal state.
5. Open `/admin/workers/` as a superuser for one dashboard across thread and Celery execution.
6. Use `/admin/celery/` to inspect Celery configuration, live workers, queues, and active tasks.
7. Use `/admin/errors/` for durable failed-task groups and the UI/API progress endpoint for run state.

The Celery overview performs no broker call, so it remains fast when workers are stopped. The worker, queue,
and task tabs use live inspection. **A busy `solo` worker cannot answer inspection until its current
task finishes**: an empty list or timeout is not proof that the worker stopped. The worker dashboard
therefore says **NO REPLY** and continues showing durable database task activity. Solo executes one
document at a time even if a larger concurrency was configured. Filesystem transport is for local,
single-host development; validate monitoring on the deployment broker before relying on live inspection.

`/admin/cache/`, `/admin/workers/`, and `/admin/errors/` are always present. `/admin/celery/` requires
`.[celery]`; `/admin/redis/` requires `.[redis]`. Missing optional panels are hidden from Operations and
return 404 if opened directly. The Redis inspector shows setup guidance until a Redis cache is configured;
it does not start Redis. Tests for Redis-specific behavior require its optional dependencies.

 Completed and failed task history remains in
`Run`/`RunItem`; this project intentionally does not add `django-celery-results` or a Celery result backend.

| Symptom | Resolution |
|---|---|
| Celery is not installed | Install `.[celery]`. |
| Redis driver is missing | Install `.[celery,redis]`. |
| Native Windows worker fails | Use `threads` or `solo`; fall back to the built-in runner or WSL2. |
| macOS logs an Objective-C `fork()` crash and `WorkerLostError` | Stop the old worker with Ctrl+C or `TERM`, set `CELERY_WORKER_POOL=solo`, and restart it. Retry failed items after the replacement worker is ready. `WORKER_DELIVERY_LIMIT` means automatic redelivery has stopped. |
| SQLite reports `database is locked` | The built-in thread runner executes inline and SQLite uses immediate transactions with a 30-second wait. Stop extra writers or disable profiling; move to Oracle for concurrent deployments. |
| A local run is interrupted | Unfinished items are marked `EXECUTION_INTERRUPTED` and retryable. Open the run and retry the failed documents; completed items are preserved. |
| Filesystem tasks remain queued | Confirm Django and the worker use the same settings, spool path, OS user, and permissions. |
| Run stage is `dispatch_failed` | Restore the broker and execute the run again; completed items will not be duplicated. |
| Item reaches `WORKER_DELIVERY_LIMIT` | Inspect worker exits or hard timeouts, correct the cause, then manually retry the failed item. |

## Official references

- [Python: macOS fork safety](https://docs.python.org/3.12/library/multiprocessing.html#contexts-and-start-methods)
- [Celery workers](https://docs.celeryq.dev/en/stable/userguide/workers.html)
- [Celery concurrency](https://docs.celeryq.dev/en/stable/userguide/concurrency/)
- [Celery task retry and acknowledgement](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Kombu filesystem transport](https://docs.celeryq.dev/projects/kombu/en/stable/reference/kombu.transport.filesystem.html)
