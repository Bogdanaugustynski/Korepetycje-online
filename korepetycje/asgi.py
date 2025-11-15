import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "korepetycje.settings")

from .routing import application  # noqa: E402
