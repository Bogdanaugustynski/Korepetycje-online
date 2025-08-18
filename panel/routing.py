from django.urls import re_path
from .consumers import VirtualRoomConsumer

websocket_urlpatterns = [
    re_path(r'ws/virtual_room/', VirtualRoomConsumer.as_asgi()),
]
