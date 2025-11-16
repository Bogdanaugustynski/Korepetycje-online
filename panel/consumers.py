import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer
from channels.db import database_sync_to_async

# 🔹 Prosty magazyn stanu tablicy w pamięci (na proces)
ROOM_STATES = {}  # {room_id: {"state": {}, "version": int}}


class VirtualRoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("virtual_room", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("virtual_room", self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        if data.get("type") == "draw":
            await self.channel_layer.group_send(
                "virtual_room",
                {
                    "type": "draw_data",
                    "x": data["x"],
                    "y": data["y"],
                },
            )

    async def draw_data(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "draw",
                    "x": event["x"],
                    "y": event["y"],
                }
            )
        )


class AudioSignalingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # room id z URL: /ws/audio/<rezerwacja_id>/
        self.room_name = self.scope["url_route"]["kwargs"]["rez_id"]
        self.group_name = f"audio_{self.room_name}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # wszystko co przyjdzie od jednej przegladarki -> broadcast do grupy (bez nadawcy)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "signal.message", "message": text_data, "sender": self.channel_name},
        )

    async def signal_message(self, event):
        # nie odsyłaj do nadawcy
        if event.get("sender") == self.channel_name:
            return
        await self.send(text_data=event["message"])


class AliboardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"aliboard_{self.room_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        room_state = ROOM_STATES.get(self.room_id)
        if room_state is not None:
            await self.send_json(
                {
                    "type": "sync",
                    "state": room_state.get("state", {}),
                    "version": room_state.get("version", 0),
                }
            )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "snapshot":
            board_state = content.get("state") or {}
            version = (ROOM_STATES.get(self.room_id, {}).get("version") or 0) + 1
            ROOM_STATES[self.room_id] = {
                "state": board_state,
                "version": version,
            }
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "aliboard.sync",
                    "state": board_state,
                    "version": version,
                    "sender_channel": self.channel_name,
                },
            )
        elif msg_type == "patch":
            patch = content.get("patch") or {}
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "aliboard.patch",
                    "patch": patch,
                    "sender_channel": self.channel_name,
                },
            )

    async def aliboard_sync(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "sync",
                "state": event.get("state") or {},
                "version": event.get("version") or 0,
            }
        )

    async def aliboard_patch(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "patch",
                "patch": event.get("patch") or {},
            }
        )
