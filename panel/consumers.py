import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer

# Prosty magazyn – na potrzeby lekcji, trzymamy patch'e w pamięci procesu
ROOM_STATE = {}  # room_id -> [patch, patch, ...]


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

        ops = ROOM_STATE.get(self.room_id, [])
        if ops:
            await self.send_json(
                {
                    "type": "snapshot",
                    "ops": ops,
                }
            )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "snapshot":
            ops = content.get("ops") or []
            ROOM_STATE[self.room_id] = list(ops)

        elif msg_type == "patch":
            patch = content.get("patch") or {}
            ROOM_STATE.setdefault(self.room_id, []).append(patch)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.patch",
                    "patch": patch,
                    "sender_channel": self.channel_name,
                },
            )

        elif msg_type == "cursor":
            cursor = content.get("cursor") or {}
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.cursor",
                    "cursor": cursor,
                    "sender_channel": self.channel_name,
                },
            )

    async def board_patch(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "patch",
                "patch": event.get("patch") or {},
            }
        )

    async def board_cursor(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "cursor",
                "cursor": event.get("cursor") or {},
            }
        )
