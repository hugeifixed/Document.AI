"""Base settings. Every environment-specific value comes from env vars
(environs), never from code. No secrets live in this file."""

import importlib.util
import os
from pathlib import Path
from typing import TypedDict, cast

from django.templatetags.static import static
from environs import Env

from config.celery_runtime import (
    broker_scheme,
    default_filesystem_root,
    default_worker_pool,
    ensure_filesystem_runtime,
    filesystem_path_error,
    filesystem_transport_options,
)
from docai.profiling import should_profile_silk_request

env = Env()
env.read_env()  # .env in CWD if present; harmless when absent

DOCAI_ENVIRONMENT = env.str("DOCAI_ENVIRONMENT", "local").strip().lower()


class DocAIConfig(TypedDict):
    PLATFORM_VERSION: str
    LAYOUT_ADAPTER: str
    LLM_ADAPTER: str
    TASK_RUNNER: str
    AZURE_DI_ENDPOINT: str
    AZURE_DI_API_VERSION: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_VERSION: str
    AZURE_OPENAI_DEPLOYMENT: str
    AZURE_TIMEOUT_S: int
    AZURE_MAX_RETRIES: int
    MAX_UPLOAD_MB: int
    MAX_PAGES: int
    MAX_SHEETS: int
    MAX_BATCH_FILES: int
    MAX_ARCHIVE_MEMBERS: int
    MAX_ARCHIVE_MEMBER_MB: int
    MAX_ARCHIVE_EXPANDED_MB: int
    MAX_ARCHIVE_COMPRESSION_RATIO: int
    CONTEXT_CHUNK_CHARS: int
    CONTEXT_CHUNK_OVERLAP: int
    WHOLE_DOC_MAX_CHARS: int
    MAX_WORKERS: int
    RAW_MODEL_RESPONSE_RETENTION_DAYS: int


BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = env.str("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
SILKY_ENABLED = env.bool("DJANGO_SILKY_ENABLED", False)

INSTALLED_APPS = [
    "unfold",  # must precede django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "corsheaders",
    "health_check",
    "dj_control_room_base",  # shared templates and tags required by the cache panel
    "dj_cache_panel",
]

# Profiling is opt-in because it adds request and SQL recording overhead.
if SILKY_ENABLED:
    INSTALLED_APPS.append("silk")

# Operational panels follow their optional runtime extras. A normal install
# remains broker-free and Redis-free; installing an extra makes its panel
# available without maintaining a second settings module.
if importlib.util.find_spec("celery") and importlib.util.find_spec("dj_celery_panel"):
    INSTALLED_APPS.append("dj_celery_panel")
if importlib.util.find_spec("redis") and importlib.util.find_spec("dj_redis_panel"):
    INSTALLED_APPS.append("dj_redis_panel")
INSTALLED_APPS.append("docai.apps.DocaiConfig")  # the reusable sub-application

MIDDLEWARE = [
    "docai.logging.middleware.CorrelationIdMiddleware",  # first: every request gets a trace id
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "docai.logging.middleware.RequestLoggingMiddleware",
]
if SILKY_ENABLED:
    MIDDLEWARE.append("silk.middleware.SilkyMiddleware")

ROOT_URLCONF = "config.urls"
CSRF_FAILURE_VIEW = "docai.api.boundaries.csrf_failure"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "config" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

# Local relational DB for development; Oracle/Postgres via env in higher envs.
DATABASES = {
    "default": env.dj_db_url(
        "DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'data' / 'docai.sqlite3'}"
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"  # unused: all PKs are UUIDs
if "sqlite" in DATABASES["default"]["ENGINE"]:
    sqlite_options = DATABASES["default"].setdefault("OPTIONS", {})
    sqlite_options.setdefault("timeout", 30)
    # A deferred read-then-write transaction can fail immediately instead of
    # honoring timeout. IMMEDIATE acquires the write reservation up front.
    sqlite_options.setdefault("transaction_mode", "IMMEDIATE")

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ------------------------------------------------------------------ storage
# Originals + immutable processing artifacts. Django's storage abstraction is
# the extension point: swap STORAGES["docai"] to an Azure Blob backend later.
DOCAI_DATA_DIR = Path(env.str("DOCAI_DATA_DIR", str(BASE_DIR / "data")))
MEDIA_ROOT = DOCAI_DATA_DIR / "media"
MEDIA_URL = "media/"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# ------------------------------------------------------------------ DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "docai.api.authentication.ChallengeSessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["docai.api.envelope.EnvelopeJSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "docai.api.pagination.StandardPagination",
    "PAGE_SIZE": env.int("DOCAI_PAGE_SIZE", 25),
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "docai.api.pagination.StableOrderingFilter",
    ],
    "EXCEPTION_HANDLER": "docai.api.exception_handler.docai_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "docai.api.openapi.DocAIAutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": env.str("DOCAI_THROTTLE_USER", "600/min"),
        "anon": env.str("DOCAI_THROTTLE_ANON", "60/min"),
    },
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "ALLOWED_VERSIONS": ["v1"],
    "DEFAULT_VERSION": "v1",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "DocAI Platform API",
    "VERSION": "1.0.0",
    "OAS_VERSION": "3.2.0",
    "DESCRIPTION": """
API for the complete document-processing lifecycle: ingest, configure, process, review, label, evaluate, and export.

### Start here

1. Sign in through the application, or use **Authorize** with Basic authentication when it is enabled for local API exploration.
2. Choose or create a **project**, then a **dataset**, and upload documents to that dataset.
3. Create and approve a **workflow version**. `GET /api/v1/workflows/types/` supplies the JSON schema for each workflow type.
4. `POST /api/v1/runs/` with matching project, workflow, and dataset UUIDs. Set `execute` to `false` to create the run without starting it.
5. Poll the run's `progress` resource when the response is `202`, then inspect results under run items, segments, classifications, and fields.
6. Review uncertain results, create ground truth, evaluate the run, and export JSON, CSV, or XLSX.

The Swagger page uses the current host, so `/api/docs/` also works through the Vite development proxy at port 5173. With a browser session, Swagger includes same-origin cookies and Django's CSRF header for unsafe requests.

### Authentication and roles

The frontend and API use the same Django session. `GET /api/v1/auth/session/` checks the session and establishes the CSRF cookie; login and logout are explicit endpoints. Basic authentication is also available to API clients.

Role memberships are independent. A user needs the role named on an operation (shown as `x-required-role`), while superusers have all roles:

* **viewer** — read-only access; sensitive document values are masked
* **operator** — upload, configure, and run processing; may view document content
* **reviewer** — review, label, split, and merge; may view document content
* **approver** — approve governed configurations and promote reviewed values to ground truth

### Response and error contract

Successful JSON responses use one envelope, including paginated results:

```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": {},
  "trace_id": "f7b35ddcd256484f"
}
```

Errors use a stable `error_code`, safe message, structured details, and the same trace ID:

```json
{
  "success": false,
  "message": "Validation failed.",
  "errors": [
    {"field": "field", "message": "This field is required.", "code": "required"}
  ],
  "error_code": "VALIDATION_ERROR",
  "trace_id": "f7b35ddcd256484f"
}
```

Every response also returns `X-Request-ID`. Send an alphanumeric `X-Request-ID` of at most 32 characters to correlate a client operation with API, service, adapter, and worker logs. Otherwise the server creates one.

List endpoints use `page` and `page_size` (default 25, maximum 200) and return `count`, `page`, `page_size`, `total_pages`, and `results` inside `data`. Resource-specific filters, full-text `search`, and allowed `ordering` fields appear on each operation.

Configuration objects are versioned for reproducibility. Runs snapshot and hash the versions they execute. A `202` response means work was accepted by the asynchronous Celery runner; use the response's `Location` header or the progress endpoint to monitor it. Sync and thread runners finish before returning.
""",
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
    "COMPONENT_SPLIT_REQUEST": True,
    "TAGS": [
        {
            "name": "Authentication",
            "description": "Session lifecycle, current user, roles, and active runtime adapters.",
        },
        {
            "name": "Workspace",
            "description": "Projects, datasets, source documents, originals, and normalized layouts.",
        },
        {
            "name": "Configuration",
            "description": "Versioned categories, schemas, prompts, model settings, templates, and workflows.",
        },
        {
            "name": "Processing",
            "description": "Run lifecycle, per-document work items, segments, progress, and metrics.",
        },
        {
            "name": "Review & labeling",
            "description": "Human classification and field review, provenance history, and ground truth.",
        },
        {
            "name": "Evaluation & export",
            "description": "Quality measurements against final ground truth and downloadable run packages.",
        },
        {
            "name": "Operations & audit",
            "description": "Operational counts and immutable audit events correlated by request ID.",
        },
    ],
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "displayRequestDuration": True,
        "docExpansion": "none",
        "filter": True,
        "showExtensions": True,
        "showCommonExtensions": True,
        "defaultModelsExpandDepth": 1,
        "defaultModelExpandDepth": 2,
    },
    "ENUM_NAME_OVERRIDES": {
        "ConfigurationStatus": "docai.models.CONFIG_STATUS",
        "DocumentStatus": "docai.models.DOC_STATUS",
        "RunStatus": "docai.models.RUN_STATUS",
        "RunItemStatus": "docai.models.ITEM_STATUS",
        "ReviewStatus": "docai.models.REVIEW_STATUS",
        "ValidationStatus": "docai.models.VALIDATION_STATUS",
        "LabelStatus": "docai.models.LABEL_STATUS",
    },
}

CORS_ALLOWED_ORIGINS = env.list("DOCAI_CORS_ORIGINS", ["http://localhost:5173"])
CORS_ALLOW_CREDENTIALS = True
CORS_URLS_REGEX = r"^/api/.*$"
CSRF_TRUSTED_ORIGINS = env.list("DOCAI_CSRF_TRUSTED", ["http://localhost:5173"])

# ------------------------------------------------------------------ cache
# Backend-agnostic: only django.core.cache is used anywhere. Swap to RedisCache
# by settings alone. LocMem has protective limits so memory cannot grow unbounded;
# those options must not be forwarded to Redis as connection-pool arguments.
_cache_backend = env.str("DOCAI_CACHE_BACKEND", "django.core.cache.backends.locmem.LocMemCache")
_cache_location = env.str("DOCAI_CACHE_LOCATION", "docai-default")
_cache_options = {}
if _cache_backend == "django.core.cache.backends.locmem.LocMemCache":
    _cache_options = {
        "MAX_ENTRIES": env.int("DOCAI_CACHE_MAX_ENTRIES", 2000),
        "CULL_FREQUENCY": 3,
    }
CACHES = {
    "default": {
        "BACKEND": _cache_backend,
        "LOCATION": _cache_location,
        "TIMEOUT": env.int("DOCAI_CACHE_TTL", 300),
        "OPTIONS": _cache_options,
    }
}
DOCAI_CACHE_TTLS = {"dashboard": 60}

# Cache inspection includes destructive operations such as editing keys and
# flushing the entire backend, so ordinary staff accounts must not open it.
DJ_CACHE_PANEL_SETTINGS = {"REQUIRE_SUPERUSER": True}
DJ_CELERY_PANEL_SETTINGS = {
    "REQUIRE_SUPERUSER": True,
    # RunItem is the durable history; the panel should show only live Celery
    # activity rather than require django-celery-results as a second store.
    "tasks_backend": "dj_celery_panel.celery_utils.CeleryTasksInspectBackend",
}

# The dedicated Redis panel stays empty while LocMem is selected. If the
# built-in Redis cache is selected later, it inspects the same configured
# endpoint with bounded timeouts and read-only controls.
_redis_panel_instances = {}
if _cache_backend == "django.core.cache.backends.redis.RedisCache" and _cache_location.startswith(
    ("redis://", "rediss://")
):
    _redis_panel_instances["application_cache"] = {
        "description": "Django application cache",
        "url": _cache_location,
    }
DJ_REDIS_PANEL_SETTINGS = {
    "REQUIRE_SUPERUSER": True,
    "ALLOW_KEY_DELETE": False,
    "ALLOW_KEY_EDIT": False,
    "ALLOW_TTL_UPDATE": False,
    "CURSOR_PAGINATED_SCAN": True,
    "CURSOR_PAGINATED_COLLECTIONS": True,
    "socket_timeout": 2.0,
    "socket_connect_timeout": 2.0,
    "INSTANCES": _redis_panel_instances,
}
DOCAI_ERROR_PANEL_SETTINGS = {"REQUIRE_SUPERUSER": True}
DOCAI_WORKER_PANEL_SETTINGS = {"REQUIRE_SUPERUSER": True}

# The profiler records timing and SQL metadata only. Bodies stay out of its
# database because requests may contain credentials or uploaded documents.
SILKY_AUTHENTICATION = True
SILKY_AUTHORISATION = True


def _silky_superuser_only(user):
    return bool(user and user.is_superuser)


SILKY_PERMISSIONS = _silky_superuser_only
SILKY_HIDE_COOKIES = True
SILKY_SENSITIVE_KEYS = {
    "api",
    "authorization",
    "cookie",
    "csrfmiddlewaretoken",
    "key",
    "password",
    "secret",
    "set-cookie",
    "signature",
    "token",
    "username",
}
SILKY_MAX_REQUEST_BODY_SIZE = 0
SILKY_MAX_RESPONSE_BODY_SIZE = 0
SILKY_MAX_RECORDED_REQUESTS = env.int("DJANGO_SILKY_MAX_RECORDED_REQUESTS", 2000)
SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT = 10
SILKY_IGNORE_PATHS = ["/health/"]
SILKY_INTERCEPT_FUNC = should_profile_silk_request
LOGIN_URL = "/admin/login/"

# ------------------------------------------------------------------ docai platform
DOCAI: DocAIConfig = {
    "PLATFORM_VERSION": "1.0.0",
    # Adapters are selected by settings so no view/service imports a vendor SDK.
    "LAYOUT_ADAPTER": env.str("DOCAI_LAYOUT_ADAPTER", "pypdf"),  # azure_di | pypdf | fixture
    "LLM_ADAPTER": env.str("DOCAI_LLM_ADAPTER", "mock"),  # azure_openai | mock
    "TASK_RUNNER": env.str("DOCAI_TASK_RUNNER", "thread"),  # sync | thread | celery
    # Azure (identity-based; no keys). Endpoints only — credentials come from
    # DefaultAzureCredential (az login locally, managed identity deployed).
    "AZURE_DI_ENDPOINT": env.str("AZURE_DI_ENDPOINT", ""),
    "AZURE_DI_API_VERSION": env.str("AZURE_DI_API_VERSION", "2024-11-30"),
    "AZURE_OPENAI_ENDPOINT": env.str("AZURE_OPENAI_ENDPOINT", ""),
    "AZURE_OPENAI_API_VERSION": env.str("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    "AZURE_OPENAI_DEPLOYMENT": env.str("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
    "AZURE_TIMEOUT_S": env.int("AZURE_TIMEOUT_S", 60),
    "AZURE_MAX_RETRIES": env.int("AZURE_MAX_RETRIES", 3),
    # ingestion limits
    "MAX_UPLOAD_MB": env.int("DOCAI_MAX_UPLOAD_MB", 100),
    "MAX_PAGES": env.int("DOCAI_MAX_PAGES", 500),
    "MAX_SHEETS": env.int("DOCAI_MAX_SHEETS", 50),
    "MAX_BATCH_FILES": env.int("DOCAI_MAX_BATCH_FILES", 500),
    "MAX_ARCHIVE_MEMBERS": env.int("DOCAI_MAX_ARCHIVE_MEMBERS", 2000),
    "MAX_ARCHIVE_MEMBER_MB": env.int("DOCAI_MAX_ARCHIVE_MEMBER_MB", 64),
    "MAX_ARCHIVE_EXPANDED_MB": env.int("DOCAI_MAX_ARCHIVE_EXPANDED_MB", 256),
    "MAX_ARCHIVE_COMPRESSION_RATIO": env.int("DOCAI_MAX_ARCHIVE_COMPRESSION_RATIO", 100),
    # processing
    "CONTEXT_CHUNK_CHARS": env.int("DOCAI_CONTEXT_CHUNK_CHARS", 24000),
    "CONTEXT_CHUNK_OVERLAP": env.int("DOCAI_CONTEXT_CHUNK_OVERLAP", 1500),
    "WHOLE_DOC_MAX_CHARS": env.int("DOCAI_WHOLE_DOC_MAX_CHARS", 60000),
    "MAX_WORKERS": env.int("DOCAI_MAX_WORKERS", 4),
    "RAW_MODEL_RESPONSE_RETENTION_DAYS": env.int("DOCAI_RAW_RESPONSE_RETENTION_DAYS", 30),
}
DATA_UPLOAD_MAX_MEMORY_SIZE = DOCAI["MAX_UPLOAD_MB"] * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ------------------------------------------------------------------ celery (optional)
# The default application runner remains broker-free. When Celery is selected,
# local settings use a filesystem spool while non-local settings require an
# explicit broker URL. Redis requires its optional driver and an environment change.
_local_settings = os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".local")
_configured_broker = env.str("CELERY_BROKER_URL", "").strip()
CELERY_BROKER_URL = _configured_broker or ("filesystem://" if _local_settings else "")
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", 1800)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", 1500)
_default_celery_filesystem_dir = default_filesystem_root(DOCAI_DATA_DIR)
CELERY_FILESYSTEM_DIR = Path(
    os.path.expandvars(env.str("CELERY_FILESYSTEM_DIR", str(_default_celery_filesystem_dir)))
)
_broker_scheme = broker_scheme(CELERY_BROKER_URL)
CELERY_BROKER_TRANSPORT_OPTIONS: dict[str, str | int | bool]
if _broker_scheme == "filesystem":
    CELERY_BROKER_TRANSPORT_OPTIONS = cast(
        dict[str, str | int | bool],
        filesystem_transport_options(CELERY_FILESYSTEM_DIR),
    )
elif _broker_scheme in {"redis", "rediss"}:
    # Keep Redis from redelivering a legitimate long task while it is still
    # running. This exceeds the hard task limit with operational headroom.
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "visibility_timeout": env.int(
            "CELERY_BROKER_VISIBILITY_TIMEOUT",
            max(3600, CELERY_TASK_TIME_LIMIT + 300),
        )
    }
else:
    CELERY_BROKER_TRANSPORT_OPTIONS = {}
_configured_result_backend = env.str("CELERY_RESULT_BACKEND", "").strip()
# Application results and completion state live in Run/RunItem. A Celery
# result backend is therefore optional, including when Redis is the broker.
CELERY_RESULT_BACKEND = _configured_result_backend or None
_configured_worker_pool = env.str("CELERY_WORKER_POOL", "").strip()
CELERY_WORKER_POOL = (_configured_worker_pool or default_worker_pool()).lower()
_sqlite_database = "sqlite" in DATABASES["default"]["ENGINE"]
CELERY_WORKER_CONCURRENCY = env.int(
    "CELERY_WORKER_CONCURRENCY", 1 if _sqlite_database else DOCAI["MAX_WORKERS"]
)
if (
    DOCAI["TASK_RUNNER"] == "celery"
    and broker_scheme(CELERY_BROKER_URL) == "filesystem"
    and filesystem_path_error(CELERY_FILESYSTEM_DIR) is None
):
    ensure_filesystem_runtime(CELERY_FILESYSTEM_DIR)

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_MAX_RETRIES = env.int("CELERY_TASK_MAX_RETRIES", 3)
CELERY_TASK_MAX_DELIVERIES = env.int("CELERY_TASK_MAX_DELIVERIES", CELERY_TASK_MAX_RETRIES + 2)
CELERY_TASK_RETRY_BACKOFF_SECONDS = env.int("CELERY_TASK_RETRY_BACKOFF_SECONDS", 15)
CELERY_TASK_RETRY_BACKOFF_MAX_SECONDS = env.int("CELERY_TASK_RETRY_BACKOFF_MAX_SECONDS", 600)
CELERY_TASK_DEFAULT_QUEUE = "docai"
CELERY_TASK_QUEUES: dict[str, dict[str, object]] = {"docai": {}}
CELERY_IMPORTS = ("docai.tasks.celery_tasks",)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_PUBLISH_RETRY = True
CELERY_TASK_PUBLISH_RETRY_POLICY = {
    "max_retries": 5,
    "interval_start": 0,
    "interval_step": 0.5,
    "interval_max": 3,
}

# ------------------------------------------------------------------ logging (loguru)
DOCAI_LOG_JSON = env.bool("DOCAI_LOG_JSON", False)
DOCAI_LOG_LEVEL = env.str("DOCAI_LOG_LEVEL", "INFO")
DOCAI_SLOW_REQUEST_MS = env.float("DOCAI_SLOW_REQUEST_MS", 1000.0)
DOCAI_LOG_DIR = DOCAI_DATA_DIR / "logs"
LOGGING_CONFIG = None  # loguru takes over in docai.logging.setup (called from AppConfig.ready)

UNFOLD = {
    "SITE_TITLE": "DocAI Admin",
    "SITE_HEADER": "DocAI Platform",
    "STYLES": [lambda request: static("docai/css/admin-theme.css")],
    "SIDEBAR": {
        "show_search": True,
        "navigation": "docai.navigation.sidebar_navigation",
    },
    "COLORS": {
        # Warm accents; neutral surfaces and semantic status colors use the defaults.
        "primary": {
            "50": "#FFF8F1",
            "100": "#FFF0DD",
            "200": "#FFDDB5",
            "300": "#FFC17E",
            "400": "#FA9A48",
            "500": "#F58025",
            "600": "#BD530D",
            "700": "#9F410D",
            "800": "#803510",
            "900": "#652C12",
            "950": "#351608",
        },
    },
}

# db_comment/db_table_comment are applied on Oracle/PostgreSQL/MySQL; SQLite (local dev)
# ignores them. Silence the informational checks so local output stays readable.
SILENCED_SYSTEM_CHECKS = ["fields.W163", "models.W046"]
