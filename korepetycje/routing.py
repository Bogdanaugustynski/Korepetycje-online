# korepetycje_django_gotowy_projekt/routing.py
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack

import aliboard.routing  # lub panel.routing, jeśli tam trzymasz

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            aliboard.routing.websocket_urlpatterns
        )
    ),
})
