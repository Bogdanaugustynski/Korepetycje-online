import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer
from django.utils import timezone

from .models import AliboardSnapshot

# Prosty magazyn stanu tablicy (na potrzeby pojedynczej instancji worker)
ROOM_STATES = {}  # room_id -> {"elements": [...], "grid": {...}}


@sync_to_async
def load_snapshot(room_id):
    try:
        snap = AliboardSnapshot.objects.get(room_id=room_id)
        return snap.data
    except AliboardSnapshot.DoesNotExist:
        return None


@sync_to_async
def save_snapshot(room_id, state):
    AliboardSnapshot.objects.update_or_create(
        room_id=room_id,
        defaults={
            "data": state,
            "updated_at": timezone.now(),
        },
    )


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
        self.room_name = self.scope["url_route"]["kwargs"]["rez_id"]
        self.group_name = f"audio_{self.room_name}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "signal.message", "message": text_data, "sender": self.channel_name},
        )

    async def signal_message(self, event):
        if event.get("sender") == self.channel_name:
            return
        await self.send(text_data=event["message"])


class AliboardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"aliboard_{self.room_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        if self.room_id not in ROOM_STATES:
            data = await load_snapshot(self.room_id)
            if data is None:
                ROOM_STATES[self.room_id] = {"elements": [], "grid": {"gridSize": 0, "kind": "grid"}}
            else:
                ROOM_STATES[self.room_id] = data

        state = ROOM_STATES[self.room_id]
        await self.send_json(
            {
                "type": "snapshot",
                "elements": state.get("elements", []),
                "grid_state": state.get("grid", {"gridSize": 0, "kind": "grid"}),
            }
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        state = ROOM_STATES.setdefault(self.room_id, {"elements": [], "grid": {"gridSize": 0, "kind": "grid"}})
        elements = state.setdefault("elements", [])

        if msg_type == "element_add":
            element = content.get("element") or {}
            element_id = element.get("id")
            if not element_id:
                return
            elements[:] = [el for el in elements if el.get("id") != element_id]
            elements.append(element)
            await save_snapshot(self.room_id, state)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.element_add",
                    "element": element,
                    "sender_channel": self.channel_name,
                },
            )

        elif msg_type == "element_update":
            element = content.get("element") or {}
            element_id = element.get("id")
            if not element_id:
                return
            replaced = False
            for idx, existing in enumerate(elements):
                if existing.get("id") == element_id:
                    elements[idx] = element
                    replaced = True
                    break
            if not replaced:
                elements.append(element)
            await save_snapshot(self.room_id, state)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.element_update",
                    "element": element,
                    "sender_channel": self.channel_name,
                },
            )

        elif msg_type == "element_remove":
            element = content.get("element") or {}
            element_id = content.get("id") or element.get("id")
            if not element_id:
                return
            elements[:] = [el for el in elements if el.get("id") != element_id]
            await save_snapshot(self.room_id, state)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.element_remove",
                    "id": element_id,
                    "sender_channel": self.channel_name,
                },
            )

        elif msg_type == "grid_state":
            grid = {
                "gridSize": content.get("gridSize", 0),
                "kind": content.get("kind", "grid"),
            }
            state["grid"] = grid
            await save_snapshot(self.room_id, state)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.grid_state",
                    "grid": grid,
                    "sender_channel": self.channel_name,
                },
            )

        elif msg_type == "snapshot_request":
            await self.send_json(
                {
                    "type": "snapshot",
                    "elements": state.get("elements", []),
                    "grid_state": state.get("grid", {"gridSize": 0, "kind": "grid"}),
                }
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

        elif msg_type == "chat_message":
            text = (content.get("text") or "").strip()
            if not text:
                return

            user = self.scope["user"]
            user_id = user.id if user.is_authenticated else None
            author_role = "teacher" if getattr(user, "is_teacher", False) else "student"

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.chat_message",
                    "text": text,
                    "author_id": user_id,
                    "author_role": author_role,
                },
            )

        elif msg_type == "call_signal":
            action = content.get("action") or "ring"
            from_id = content.get("from_id")

            user = self.scope["user"]
            if getattr(user, "is_teacher", False):
                from_role = "teacher"
            else:
                from_role = "student"

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.call_signal",
                    "action": action,
                    "from_id": from_id,
                    "from_role": from_role,
                },
            )

        elif msg_type == "webrtc_offer":
            sdp = content.get("sdp")
            if not sdp:
                return
            user = self.scope["user"]
            user_id = user.id if user.is_authenticated else None

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.webrtc_offer",
                    "sdp": sdp,
                    "from_id": user_id,
                },
            )

        elif msg_type == "webrtc_answer":
            sdp = content.get("sdp")
            if not sdp:
                return
            user = self.scope["user"]
            user_id = user.id if user.is_authenticated else None

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.webrtc_answer",
                    "sdp": sdp,
                    "from_id": user_id,
                },
            )

        elif msg_type == "webrtc_ice_candidate":
            candidate = content.get("candidate")
            if not candidate:
                return
            user = self.scope["user"]
            user_id = user.id if user.is_authenticated else None

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.webrtc_ice_candidate",
                    "candidate": candidate,
                    "from_id": user_id,
                },
            )

    async def board_element_add(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "element_add",
                "element": event.get("element") or {},
            }
        )

    async def board_element_update(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "element_update",
                "element": event.get("element") or {},
            }
        )

    async def board_element_remove(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "element_remove",
                "id": event.get("id"),
            }
        )

    async def board_grid_state(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "grid_state",
                "gridSize": event.get("grid", {}).get("gridSize", 0),
                "kind": event.get("grid", {}).get("kind", "grid"),
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

    async def board_chat_message(self, event):
        await self.send_json(
            {
                "type": "chat_message",
                "text": event.get("text") or "",
                "author_id": event.get("author_id"),
                "author_role": event.get("author_role") or "unknown",
            }
        )

    async def board_call_signal(self, event):
        await self.send_json(
            {
                "type": "call_signal",
                "action": event.get("action"),
                "from_id": event.get("from_id"),
                "from_role": event.get("from_role"),
            }
        )

    async def board_webrtc_offer(self, event):
        await self.send_json(
            {
                "type": "webrtc_offer",
                "sdp": event.get("sdp"),
                "from_id": event.get("from_id"),
            }
        )

    async def board_webrtc_answer(self, event):
        await self.send_json(
            {
                "type": "webrtc_answer",
                "sdp": event.get("sdp"),
                "from_id": event.get("from_id"),
            }
        )

    async def board_webrtc_ice_candidate(self, event):
        await self.send_json(
            {
                "type": "webrtc_ice_candidate",
                "candidate": event.get("candidate"),
                "from_id": event.get("from_id"),
            }
        )
