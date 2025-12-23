
import django.db.models.deletion
from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("panel", "0036_aliboardsnapshot_aliboardchatmessage"),
    ]

    operations = [
        migrations.CreateModel(
            name="AliboardChatReadState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("room_id", models.CharField(db_index=True, max_length=255)),
                ("last_read_at", models.DateTimeField()),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aliboard_read_states",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("room_id", "user")},
                "indexes": [models.Index(fields=["room_id"], name="panel_alibo_room_id_idx")],
            },
        ),
    ]
