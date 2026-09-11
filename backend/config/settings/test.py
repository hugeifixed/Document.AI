from .base import *  # noqa: F401,F403

DOCAI_ENVIRONMENT = "test"
DEBUG = False
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DOCAI["LAYOUT_ADAPTER"] = "pypdf"
DOCAI["LLM_ADAPTER"] = "mock"
DOCAI["TASK_RUNNER"] = "sync"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}
