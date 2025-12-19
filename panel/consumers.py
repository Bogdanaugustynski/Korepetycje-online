import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer
from django.utils import timezone

from .models import AliboardChatMessage

# Prosty magazyn elementĂłw tablicy (na potrzeby pojedynczej instancji)
ROOM_STATE = {}  # room_id -> {"elements": {element_id: element_json}}
ROOM_CHANNELS = {}  # room_id -> {user_id: channel_name}
ROOM_GRID_STATE = {}  # { room_id: {"gridSize": int|str, "kind": "grid"|"tech"|"none"} }


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
        user = self.scope["user"]
        self.user_id = self._normalize_user_id(user.id) if user.is_authenticated else None

        await self.accept()
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        self._register_channel()

        history_qs = (
            AliboardChatMessage.objects.filter(room_id=self.room_id)
            .select_related("author")
            .order_by("-created_at")[:100]
        )
        history = await database_sync_to_async(list)(history_qs)
        history.reverse()

        for msg in history:
            author = msg.author
            author_name = None
            author_id = None
            if author:
                author_id = author.id
                full = (author.get_full_name() or "").strip()
                author_name = full or author.username

            await self.send_json(
                {
                    "type": "chat_message",
                    "text": msg.text,
                    "author_id": author_id,
                    "author_name": author_name,
                    "created_at": timezone.localtime(msg.created_at).isoformat(),
                    "is_history": True,
                }
            )

        state = ROOM_STATE.get(self.room_id)
        if state and state.get("elements"):
            await self.send_json(
                {
                    "type": "snapshot",
                    "elements": list(state["elements"].values()),
                }
            )

        grid_state = ROOM_GRID_STATE.get(self.room_id)
        if grid_state:
            await self.send_json(
                {
                    "type": "grid_state",
                    "gridSize": grid_state.get("gridSize"),
                    "kind": grid_state.get("kind") or "grid",
                }
            )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        self._unregister_channel()

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        state = ROOM_STATE.setdefault(self.room_id, {"elements": {}})

        if msg_type == "element_add":
            element = content.get("element") or {}
            element_id = element.get("id")
            if not element_id:
                return
            state["elements"][element_id] = element
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
            state["elements"][element_id] = element
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.element_update",
                    "element": element,
                    "sender_channel": self.channel_name,
                },
            )

        elif msg_type == "element_remove":
            element_id = content.get("id")
            if not element_id:
                return
            state["elements"].pop(element_id, None)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.element_remove",
                    "id": element_id,
                    "sender_channel": self.channel_name,
                },
            )

        elif msg_type == "grid_state":
            grid_size = content.get("gridSize")
            kind = content.get("kind") or "grid"

            ROOM_GRID_STATE[self.room_id] = {
                "gridSize": grid_size,
                "kind": kind,
            }

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "broadcast_grid_state",
                    "gridSize": grid_size,
                    "kind": kind,
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

        elif msg_type == "chat_message":
            text = (content.get("text") or "").strip()
            if not text:
                return

            user = self.scope.get("user")
            author = user if user and getattr(user, "is_authenticated", False) else None
            author_role = "teacher" if getattr(user, "is_teacher", False) else "student"

            msg_obj = await database_sync_to_async(AliboardChatMessage.objects.create)(
                room_id=self.room_id,
                author=author,
                text=text[:500],
            )

            author_id = author.id if author else None
            author_name = None
            if author:
                full = (author.get_full_name() or "").strip()
                author_name = full or author.username

            payload = {
                "type": "broadcast_chat_message",
                "text": msg_obj.text,
                "author_id": author_id,
                "author_name": author_name,
                "author_role": author_role,
                "created_at": timezone.localtime(msg_obj.created_at).isoformat(),
            }

            await self.channel_layer.group_send(self.group_name, payload)
            return

        elif msg_type == "chat_mic_state":
            muted = bool(content.get("muted"))
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "broadcast.chat_mic_state",
                    "muted": muted,
                    "user_id": self.user_id,
                },
            )
            return

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

        elif msg_type == "audio_mode":
            mode = content.get("mode")
            if not mode:
                return

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "broadcast.audio_mode",
                    "mode": mode,
                    "from_id": self.user_id,
                },
            )

        elif msg_type and msg_type.startswith("voice:"):
            payload = {**content, "from_id": self.user_id}
            to_id_raw = content.get("to_id")
            to_id = self._normalize_user_id(to_id_raw)

            if to_id_raw is not None:
                if to_id is None:
                    return

                target_channel = self._get_channel_for_user(to_id)
                if target_channel:
                    await self.channel_layer.send(
                        target_channel,
                        {
                            "type": "direct.voice",
                            "payload": payload,
                        },
                    )
            else:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "broadcast.voice",
                        "payload": payload,
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

    async def board_cursor(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        await self.send_json(
            {
                "type": "cursor",
                "cursor": event.get("cursor") or {},
            }
        )

    async def broadcast_chat_message(self, event):
        await self.send_json(
            {
                "type": "chat_message",
                "text": event.get("text") or "",
                "author_id": event.get("author_id"),
                "author_name": event.get("author_name") or "Użytkownik",
                "author_role": event.get("author_role") or "unknown",
                "created_at": event.get("created_at"),
            }
        )

    async def broadcast_chat_mic_state(self, event):
        await self.send_json(
            {
                "type": "chat_mic_state",
                "user_id": event.get("user_id"),
                "muted": bool(event.get("muted")),
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

    async def broadcast_audio_mode(self, event):
        await self.send_json(
            {
                "type": "audio_mode",
                "mode": event.get("mode"),
                "from_id": event.get("from_id"),
            }
        )

    async def broadcast_grid_state(self, event):
        await self.send_json(
            {
                "type": "grid_state",
                "gridSize": event.get("gridSize"),
                "kind": event.get("kind"),
            }
        )

    async def broadcast_voice(self, event):
        await self.send_json(event.get("payload") or {})

    async def direct_voice(self, event):
        await self.send_json(event.get("payload") or {})

    def _normalize_user_id(self, raw):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _register_channel(self):
        if self.user_id is None:
            return
        room_channels = ROOM_CHANNELS.setdefault(self.room_id, {})
        room_channels[self.user_id] = self.channel_name

    def _unregister_channel(self):
        if self.user_id is None:
            return
        room_channels = ROOM_CHANNELS.get(self.room_id)
        if not room_channels:
            return
        room_channels.pop(self.user_id, None)
        if not room_channels:
            ROOM_CHANNELS.pop(self.room_id, None)

    def _get_channel_for_user(self, user_id):
        room_channels = ROOM_CHANNELS.get(self.room_id) or {}
        return room_channels.get(user_id)

