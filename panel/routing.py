from django.urls import re_path

from .consumers import (
    AliboardConsumer,
    AudioSignalingConsumer,
    VirtualRoomConsumer,
)
from .consumers_prod import AliboardConsumer as AliboardProdConsumer


websocket_urlpatterns = [
    re_path(r"ws/virtual_room/$", VirtualRoomConsumer.as_asgi()),
    re_path(r"ws/audio/(?P<rez_id>\d+)/$", AudioSignalingConsumer.as_asgi()),
    re_path(r"ws/aliboard-test/(?P<room_id>[\w\-]+)/$", AliboardConsumer.as_asgi()),
    re_path(r"ws/aliboard/(?P<room_id>[\w\-]+)/$", AliboardProdConsumer.as_asgi()),
]
