from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_reviewer",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Ve las galerías privadas y baja los originales sin logos. "
                    "No entra al panel de administración."
                ),
                verbose_name="invitado (solo ver/descargar)",
            ),
        ),
    ]
