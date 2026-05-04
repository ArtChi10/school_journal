import os
from pathlib import Path
import importlib
from urllib.parse import parse_qs, unquote, urlparse


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "jobs",
    "validation",
    "journal_links",
    "pipeline",
    "webapp",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "admin_panel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "admin_panel.wsgi.application"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def database_from_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()
    if scheme in {"postgres", "postgresql"}:
        config = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
        }
        query = parse_qs(parsed.query)
        sslmode = (query.get("sslmode") or [""])[0]
        if sslmode:
            config["OPTIONS"] = {"sslmode": sslmode}
        return config

    if scheme == "sqlite":
        db_path = unquote(parsed.path or "")
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": db_path or BASE_DIR / "db.sqlite3",
        }

    raise ValueError("DATABASE_URL supports only postgres/postgresql/sqlite schemes")


def build_database_config() -> dict:
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if database_url:
        return database_from_url(database_url)

    postgres_host = (os.getenv("POSTGRES_HOST") or "").strip()
    if postgres_host:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "school_journal"),
            "USER": os.getenv("POSTGRES_USER", "school_journal"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": postgres_host,
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }

    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


DATABASES = {"default": build_database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = Path(os.getenv("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", SECURE_SSL_REDIRECT)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
ADMIN_LOG_CHAT_ID = os.getenv("ADMIN_LOG_CHAT_ID", "")

LOG_FILE = Path(os.getenv("APP_LOG_FILE", BASE_DIR / "logs" / "app.log"))
JOB_ERRORS_LOG_FILE = Path(os.getenv("APP_JOB_ERROR_LOG_FILE", BASE_DIR / "logs" / "jobs_errors.log"))
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
JOB_ERRORS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "admin_panel.logging_handlers.SafeStreamHandler",
            "formatter": "verbose",
        },
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_FILE),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "level": "INFO",
            "formatter": "verbose",
        },
        "job_errors_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(JOB_ERRORS_LOG_FILE),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "level": "ERROR",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "app_file"],
        "level": "INFO",
    },
    "loggers": {
        "jobs": {"handlers": ["console", "app_file", "job_errors_file"], "level": "INFO", "propagate": False},
        "pipeline": {"handlers": ["console", "app_file", "job_errors_file"], "level": "INFO", "propagate": False},
        "validation": {"handlers": ["console", "app_file", "job_errors_file"], "level": "INFO", "propagate": False},
        "notifications": {"handlers": ["console", "app_file", "job_errors_file"], "level": "INFO", "propagate": False},
    },
}


def init_sentry() -> None:
    sentry_dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not sentry_dsn:
        return

    sentry_module_spec = importlib.util.find_spec("sentry_sdk")
    if sentry_module_spec is None:
        return

    sentry_sdk = importlib.import_module("sentry_sdk")
    django_integration = importlib.import_module("sentry_sdk.integrations.django").DjangoIntegration
    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
    sentry_environment = os.getenv("SENTRY_ENVIRONMENT", "production")

    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=sentry_environment,
        traces_sample_rate=traces_sample_rate,
        integrations=[django_integration()],
        send_default_pii=False,
    )


init_sentry()
