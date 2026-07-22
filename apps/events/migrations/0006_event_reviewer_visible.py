from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0005_eventmetric"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="reviewer_visible",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Si está activado, los invitados ven este evento y bajan sus "
                    "originales sin logos."
                ),
                verbose_name="visible para invitados",
            ),
        ),
    ]
