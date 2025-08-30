import json
from channels.generic.websocket import AsyncWebsocketConsumer

class VirtualRoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add('virtual_room', self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard('virtual_room', self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        if data.get('type') == 'draw':
            await self.channel_layer.group_send(
                'virtual_room',
                {
                    'type': 'draw_data',
                    'x': data['x'],
                    'y': data['y'],
                }
            )

    async def draw_data(self, event):
        await self.send(text_data=json.dumps({
            'type': 'draw',
            'x': event['x'],
            'y': event['y']
        }))

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
        # wszystko co przyjdzie od jednej przeglądarki – broadcast do grupy (oprócz nadawcy)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "signal.message", "message": text_data, "sender": self.channel_name}
        )

    async def signal_message(self, event):
        # nie odsyłaj do nadawcy
        if event.get("sender") == self.channel_name:
            return
        await self.send(text_data=event["message"])
