from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.getenv("DEBUG", "0") == "1"
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

def _csv_env(name: str):
    val = os.getenv(name, "")
    return [x.strip() for x in val.split(",") if x.strip()]

ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS") or ["localhost", "127.0.0.1", ".onrender.com"]
CSRF_TRUSTED_ORIGINS = _csv_env("CSRF_TRUSTED_ORIGINS") or ["https://*.onrender.com"]

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

ROOT_URLCONF = "korepetycje.urls"
WSGI_APPLICATION = "korepetycje.wsgi.application"
ASGI_APPLICATION = "korepetycje.asgi.application"

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

# ===== BAZA DANYCH (twarde ignorowanie popsutej DATABASE_URL) =====
def _valid_env(name: str):
    val = os.getenv(name)
    if val and val.strip() and val.strip() != "://":
        return val.strip()
    return None

_db_url = (
    _valid_env("DATABASE_URL")
    or _valid_env("URL_BAZY_DANYCH")
    or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
)

# UŻYWAMY parse(), a NIE config(), żeby NIE czytać z ENV!
DATABASES = {
    "default": dj_database_url.parse(_db_url, conn_max_age=600),
}

# ===== CHANNELS =====
if os.getenv("REDIS_URL"):
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [os.getenv("REDIS_URL")]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

LANGUAGE_CODE = "pl-pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if (BASE_DIR / "static").exists():
    STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

LOGIN_URL = "/ukryty_admin/login/"
AUTH_PASSWORD_VALIDATORS = []

CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
