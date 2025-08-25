from pathlib import Path
import os
import dj_database_url
from dj_database_url import UnknownSchemeError  # <-- ważne

# === ŚCIEŻKI ===
BASE_DIR = Path(__file__).resolve().parent.parent

# === BEZPIECZEŃSTWO / DEBUG ===
DEBUG = os.getenv("DEBUG", "0") == "1"
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

# Hosty i CSRF (ENV → jeśli brak, domyślki dla Render)
def _csv_env(name: str):
    val = os.getenv(name, "")
    return [x.strip() for x in val.split(",") if x.strip()]

ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS") or ["localhost", "127.0.0.1", ".onrender.com"]
CSRF_TRUSTED_ORIGINS = _csv_env("CSRF_TRUSTED_ORIGINS") or ["https://*.onrender.com"]

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

# === NAZWY MODUŁÓW PROJEKTU ===
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
# Spróbuj z poprawnym ENV; jeśli złe/puste → przełącz na SQLite bez wywrotki
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
    DATABASES = {
        "default": dj_database_url.parse(_db_url, conn_max_age=600),
    }
except UnknownSchemeError:
    # Ostateczny bezpiecznik na wypadek zepsutego ENV
    DATABASES = {
        "default": dj_database_url.parse(f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600),
    }

# === CHANNELS (Redis w produkcji, InMemory lokalnie) ===
if os.getenv("REDIS_URL"):
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [os.getenv("REDIS_URL")]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# === INTERNACJONALIZACJA ===
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
MEDIA_ROOT = BASE_DIR / "media"   # Uwaga: na Render Free pliki są efemeryczne

# === LOGOWANIE / SESJE ===
LOGIN_URL = "/ukryty_admin/login/"
AUTH_PASSWORD_VALIDATORS = []

# === SECURITY HEADERS ===
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
