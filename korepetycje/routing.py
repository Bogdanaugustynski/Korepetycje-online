import os

from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "korepetycje.settings")

django_asgi_app = get_asgi_application()

try:
    from panel import routing as panel_routing
    websocket_patterns = panel_routing.websocket_urlpatterns
except Exception:
    websocket_patterns = []

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_patterns)
    ),
})
