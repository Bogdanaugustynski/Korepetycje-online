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
    # pliki S3
    "storages",
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

# === STATIC (WhiteNoise) ===
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if (BASE_DIR / "static").exists():
    STATICFILES_DIRS = [BASE_DIR / "static"]

# Django 5.2: używamy STORAGES['staticfiles'] zamiast STATICFILES_STORAGE
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    # "default" (MEDIA) dopiszemy niżej warunkowo przy USE_S3
}

# === MEDIA: S3 (OVH) jeśli ENV ustawione, inaczej lokalnie ===
USE_S3 = os.getenv("USE_S3", "0").strip() == "1"

def _env(name: str, default: str | None = None):
    v = os.getenv(name, default if default is not None else "")
    return v.strip() if isinstance(v, str) else v

if USE_S3:
    if "storages" not in INSTALLED_APPS:
        INSTALLED_APPS += ["storages"]

    # Django 4.2+/5.x: STORAGES (default = S3), staty zostają na WhiteNoise lokalnie
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"},
        # Jeśli kiedyś chcesz przenieść STATIC na S3, dodasz tu "staticfiles"
    }

    AWS_ACCESS_KEY_ID = _env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = _env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = _env("AWS_STORAGE_BUCKET_NAME")          # np. polubiszto-media
    AWS_S3_ENDPOINT_URL = _env("AWS_S3_ENDPOINT_URL", "https://s3.waw.io.cloud.ovh.net")

    # ⬅︎ KLUCZOWE: OVH oczekuje regionu wielkimi literami (WAW/GRA/SBG)
    AWS_S3_REGION_NAME = _env("AWS_S3_REGION_NAME", "WAW")             # UPPERCASE

    AWS_S3_SIGNATURE_VERSION = "s3v4"

    # ⬅︎ OVH + custom endpoint zazwyczaj działa lepiej w trybie PATH
    AWS_S3_ADDRESSING_STYLE = "path"

    # Bez publicznych ACL; podpisane linki generujemy po stronie serwera
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True

    # Te wartości przy S3 i tak nie są używane przez nasze widoki (nie wywołujemy .url)
    MEDIA_URL = "/media/"
    MEDIA_ROOT = ""
else:
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

# === SECURITY (hardening) ===
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True  # legacy/no-op w nowych przeglądarkach
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Logowanie / przekierowania
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/uczen/moje-konto/"

# Walidatory haseł (na razie wyłączone)
AUTH_PASSWORD_VALIDATORS = []

# === UPLOAD LIMITS / AVATAR ===
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024      # 2 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024      # 5 MB
FILE_UPLOAD_PERMISSIONS = 0o640

# === LOGI ===
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "webrtc": {"handlers": ["console"], "level": "INFO"},
        # "boto3": {"handlers": ["console"], "level": "WARNING"},
        # "botocore": {"handlers": ["console"], "level": "WARNING"},
    },
}

# === PŁATNOŚCI / FAKTURY ===
AUTOPAY_WEBHOOK_SECRET = os.getenv("AUTOPAY_WEBHOOK_SECRET", "change-me")
INVOICE_PLACE_DEFAULT = os.getenv("INVOICE_PLACE_DEFAULT", "Warszawa")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "PLN")

# (opcjonalnie) e-mail nadawcy
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "PolubiszTo.pl <no-reply@polubiszto.pl>")
