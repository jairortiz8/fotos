"""Guardar la confianza de detección de cada cara.

InsightFace la devuelve en cada detección y el pipeline la venía descartando
desde la Fase 4. Es la señal más barata para saber que un embedding va a ser
malo, y sin ella sólo se puede detectar después, a posteriori, mirando cómo se
comporta en la búsqueda.

Nullable a propósito: las caras ya indexadas (21k fotos en producción) no la
tienen y no se puede recuperar sin reprocesar las fotos con el modelo cargado.
De acá en adelante cada evento nuevo la trae sin costo.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("photos", "0007_faceembedding_avatar_key")]

    operations = [
        migrations.AddField(
            model_name="faceembedding",
            name="det_score",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text=(
                    "Qué tan segura está InsightFace de que esto es una cara (0-1). "
                    "Una cara con score bajo suele dar un embedding malo: encuentra "
                    "pocas fotos al umbral normal y medio evento al aflojarlo. "
                    "Nullable porque las fotos anteriores a este campo no lo tienen: "
                    "el dato se calculaba y se descartaba, y no se puede recuperar sin "
                    "reprocesar la foto."
                ),
                verbose_name="confianza de la detección",
            ),
        ),
    ]
