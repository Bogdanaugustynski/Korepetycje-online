import os
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from panel.routing import websocket_urlpatterns
import yourapp.routing

# WAŻNE: nazwa projektu to "korepetycje" – tak zostaje
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "korepetycje.settings")

django_asgi_app = get_asgi_application()

try:
    from panel import routing as panel_routing
    websocket_patterns = panel_routing.websocket_urlpatterns
except Exception:
    # jeśli routing jeszcze nie gotowy, po prostu nie podłączaj WS (nie wywali deploya)
    websocket_patterns = []

# 🔹 NOWY FRAGMENT – tak jak w instrukcji:
# po ustawieniu DJANGO_SETTINGS_MODULE importujemy gotowe `application`
# z pliku korepetycje/routing.py
from .routing import application


# 🔸 STARY BLOK ZOSTAWIAMY W KOMENTARZU (NIC NIE USUWAMY):
"""
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            yourapp.routing.websocket_urlpatterns
        )
    ),
})
"""


