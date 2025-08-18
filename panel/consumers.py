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

