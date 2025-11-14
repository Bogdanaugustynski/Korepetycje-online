from django.urls import re_path
from .consumers import VirtualRoomConsumer
from .consumers import AudioSignalingConsumer
from .consumers import AliboardConsumer

websocket_urlpatterns = [
    re_path(r'ws/virtual_room/', VirtualRoomConsumer.as_asgi()),
]

websocket_urlpatterns = [
    re_path(r"ws/audio/(?P<rez_id>\d+)/$", AudioSignalingConsumer.as_asgi()),
]

websocket_urlpatterns = [
    re_path(r"ws/aliboard/(?P<room_id>[\w\-]+)/$", AliboardConsumer.as_asgi()),
]