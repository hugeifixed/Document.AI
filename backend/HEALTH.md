# Health probes and infrastructure diagnostics

| URL | Purpose | Failed check |
| --- | --- | --- |
| `/health/live/` | Django can answer requests; no dependency calls | Process failure |
| `/health/ready/` | Database, application cache, and document storage read/write/delete | HTTP 503 |
| `/health/` | The same core checks plus configured infrastructure diagnostics | HTTP 503 |

Use **live** and **ready** for OpenShift probes. The detailed page also offers JSON, text,
OpenMetrics, Atom, and RSS. JSON/text return 503 for failures; feeds and OpenMetrics retain HTTP 200
and carry failure states in their content. All formats hide connection strings, hostnames, paths,
credentials, and raw exception messages. Additional DNS names below are public display labels.

The implementation uses django-health-check **v4**. No legacy check apps or `HEALTH_CHECK_*`
settings are needed. Set `DOCAI_HEALTH_EXTENDED_ENABLED=false` to disable all extended diagnostics.

## Redis

Redis PING appears automatically when the built-in Django Redis cache is selected, or when the
active Celery runner uses a `redis://` or `rediss://` broker. Cache replicas are checked separately.
LocMem and the filesystem broker do not trigger Redis imports or network calls. Install the existing
`redis` extra when selecting Redis. No additional health-check package is required.

PING tests connection/authentication, while the core cache check exercises application read/write.
A healthy broker does **not** prove a worker is consuming tasks; use `/admin/workers/` for that.

## Azure and other endpoint DNS

The selected `azure_di` and `azure_openai` adapters automatically add DNS checks for their configured
endpoints. Unused Azure settings with `pypdf`/`mock` do not cause network traffic. A selected adapter
with an empty endpoint fails its DNS check.

Add other explicit targets through a JSON object in the environment:

```dotenv
DOCAI_HEALTH_DNS_ENDPOINTS={"identity":"https://login.microsoftonline.com/","document_gateway":"https://documents.example.internal/health"}
DOCAI_HEALTH_TIMEOUT_SECONDS=3
```

Names must be lowercase letters, digits, or underscores, start with a letter, and be at most 40
characters. Up to 16 additional targets are supported. Use descriptive names, not secrets or hosts.
Only the URL's hostname is resolved (an IPv4/A lookup using the runtime's configured DNS servers).
Paths are **not requested**. Private Azure endpoints require the container's private DNS configuration.
DNS probes do not traverse HTTP proxies. A proxy may resolve Azure hosts on the application's behalf;
see [Azure networking](AZURE_NETWORK.md) before interpreting local DNS failures in that topology.

DNS success does not verify TLS, routing/firewall access to HTTPS, credentials/RBAC, model deployment,
quota, or extraction. These remain live integration smoke tests. Probes never upload documents or
invoke DI/LLM APIs. DNS and Redis checks run concurrently with a per-check network time budget of
3 seconds by default (configurable up to 30 seconds); they do not affect web readiness. An unavailable
Redis **application cache** still fails readiness through the existing core cache check.

## Data disk and NAS

By default, disk capacity is measured at `DOCAI_DATA_DIR` and fails at 90% used. The status page shows
the percentage and threshold. It never creates the directory or falls back to another disk.
The existing document storage check tests read/write/delete using `STORAGES["default"]`.

For a Linux/OpenShift NAS volume mounted at `/mnt/docai`:

```dotenv
DOCAI_DATA_DIR=/mnt/docai/data
DOCAI_HEALTH_DISK_PATH=/mnt/docai
DOCAI_HEALTH_DISK_MAX_USED_PERCENT=90
DOCAI_HEALTH_DISK_REQUIRE_MOUNT=true
```

Provision the data directory on the volume first. The mount guard checks the **actual mount root**;
a subdirectory such as `/mnt/docai/data` is not itself a mount point. It detects a missing mount even
when an empty local directory remains. This is an availability check, not verification of the NAS
server's identity or expected volume ID.

For Windows, use `DOCAI_DATA_DIR=C:/DocAI/data` or the institution's mounted share path. Leave
`DOCAI_HEALTH_DISK_PATH` blank and `DOCAI_HEALTH_DISK_REQUIRE_MOUNT=false` for an ordinary directory.
Paths use Python's cross-platform filesystem APIs. Validate mount detection on the deployed volume
type before enabling the guard (including UNC shares or container subPath/bind mounts).

Changing the health path only changes the check; it does not relocate documents. Storage capacity
comes from the OS and may not describe NAS user quotas. Configure NAS/client I/O timeouts and
monitor the storage system itself: a stuck filesystem syscall cannot be reliably cancelled by the
application's DNS/Redis timeout. Object storage uses its Django backend for read/write probes; the
disk check continues to cover the local data/scratch directory, not the bucket's capacity.
