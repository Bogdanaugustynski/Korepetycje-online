# settings.py
from pathlib import Path
import os
import dj_database_url
from dj_database_url import UnknownSchemeError

# === ŚCIEŻKI ===
BASE_DIR = Path(__file__).resolve().parent.parent

# === DEBUG / SECRET ===
DEBUG = os.getenv("DEBUG", "0") == "1"
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

# === HOSTS / CSRF ===
def _csv_env(name: str):
    val = os.getenv(name, "")
    return [x.strip() for x in val.split(",") if x.strip()]

ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS") or [
    "localhost",
    "127.0.0.1",
    "korepetycje-online.onrender.com",
    "polubiszto.pl",
    "www.polubiszto.pl",
    ".onrender.com",
]

CSRF_TRUSTED_ORIGINS = _csv_env("CSRF_TRUSTED_ORIGINS") or [
    "https://korepetycje-online.onrender.com",
    "https://polubiszto.pl",
    "https://www.polubiszto.pl",
    "https://*.onrender.com",
]

# === APLIKACJE ===
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "panel",
    "channels",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# === MIDDLEWARE ===
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

# === URLCONF / WSGI / ASGI ===
ROOT_URLCONF = "korepetycje.urls"
WSGI_APPLICATION = "korepetycje.wsgi.application"
ASGI_APPLICATION = "korepetycje.asgi.application"

# === SZABLONY ===
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# === BAZA DANYCH ===
def _valid_env(name: str):
    val = os.getenv(name)
    if not val:
        return None
    val = val.strip()
    if not val or val == "://":
        return None
    return val

_db_url = (
    _valid_env("DATABASE_URL")
    or _valid_env("URL_BAZY_DANYCH")
    or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
)

try:
    DATABASES = {"default": dj_database_url.parse(_db_url, conn_max_age=600)}
except UnknownSchemeError:
    DATABASES = {"default": dj_database_url.parse(f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600)}

# === CHANNELS (Redis w prod, InMemory lokalnie) ===
def _valid_redis_url(u: str | None) -> bool:
    if not u:
        return False
    u = u.strip().lower()
    # akceptuj tylko prawidłowe schematy Redis
    return u.startswith(("redis://", "rediss://", "unix://"))

REDIS_URL = os.getenv("REDIS_URL")

if _valid_redis_url(REDIS_URL):
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# === CACHE (wspólny dla WebRTC signaling) ===
if _valid_redis_url(REDIS_URL):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": 600,
        }
    }
else:
    # Bezpieczny fallback: jeden proces => wspólny cache plikowy
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": BASE_DIR / "webrtc_cache",
            "TIMEOUT": 600,
        }
    }

# === I18N / TZ ===
LANGUAGE_CODE = "pl-pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

# === STATIC / MEDIA ===
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if (BASE_DIR / "static").exists():
    STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"  # (na darmowym Render pliki efemeryczne)

# === SECURITY ===
LOGIN_URL = "/login/"
AUTH_PASSWORD_VALIDATORS = []
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
X_FRAME_OPTIONS = "DENY"

# === LOGI (diagnostyka WebRTC) ===
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "webrtc": {"handlers": ["console"], "level": "INFO"},
    },
}
