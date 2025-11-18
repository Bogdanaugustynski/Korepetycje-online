import json

from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer

# Prosty magazyn elementĂłw tablicy (na potrzeby pojedynczej instancji)
ROOM_STATE = {}  # room_id -> {"elements": {element_id: element_json}}


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

        state = ROOM_STATE.get(self.room_id)
        if state and state.get("elements"):
            await self.send_json(
                {
                    "type": "snapshot",
                    "elements": list(state["elements"].values()),
                }
            )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        state = ROOM_STATE.setdefault(self.room_id, {"elements": {}})


        # đź”ą Rysowanie â€“ elementy
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

        # đź”ą Kursory
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

        # đź”ą CZAT â€“ NOWE
        # CZAT -- NOWE
        elif msg_type == "chat_message":
            text = (content.get("text") or "").strip()
            if not text:
                return

            user = self.scope.get("user")
            user_id = user.id if getattr(user, "is_authenticated", False) else None
            author_role = "teacher" if getattr(user, "is_teacher", False) else "student"

            # Wysylamy do wszystkich w pokoju
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.chat_message",   # -> metoda board_chat_message
                    "text": text,
                    "author_id": user_id,
                    "author_role": author_role,
                },
            )

        elif msg_type == "call_signal":
            action = content.get("action") or "ring"
            from_id = content.get("from_id")
            from_role = content.get("from_role") or "unknown"

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "board.call_signal",
                    "action": action,
                    "from_id": from_id,
                    "from_role": from_role,
                },
            )

    # đź”ą Handlery rysowania
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

    # Đ«"ďż˝ NOWE: handler czatu
    async def board_chat_message(self, event):
        """
        Odbiera wiadomosc z group_send i rozsyla ja do wszystkich klientow w pokoju,
        lacznie z nadawca (front oczekuje na echo z serwera).
        """
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
