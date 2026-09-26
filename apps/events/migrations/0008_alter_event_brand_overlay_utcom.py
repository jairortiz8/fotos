"""Agrega UTCOM 2026 a las opciones de overlay de marca.

Sólo cambia `choices`: no toca la columna ni los datos. La plantilla vive en
`apps.photos.overlays.TEMPLATES`; acá sólo se habilita en el desplegable del
dashboard.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("events", "0007_alter_event_brand_overlay")]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="brand_overlay",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Ninguno (watermark normal)"),
                    ("surf_city", "Surf City (logos en las esquinas)"),
                    ("septimo_cep", "SÉPTIMO x CEP (5 logos abajo)"),
                    ("utcom_2026", "UTCOM 2026 (logo centrado abajo)"),
                ],
                default="",
                help_text=(
                    "Pega los logos del evento en las esquinas de abajo de cada foto. "
                    "Se aplica SOLO a este evento."
                ),
                max_length=32,
                verbose_name="logos de marca en las fotos",
            ),
        ),
    ]
