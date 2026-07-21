"""Tabla de métricas agregadas por hora (curvas del dashboard) + backfill de subidas.

Las curvas de descargas/vistas/búsquedas sólo se pueden llenar hacia adelante
(nunca se guardó su historial — decisión de privacidad, sin SearchLog). Las
SUBIDAS sí tienen timestamp (`Photo.created_at`), así que las reconstruimos acá
para que los eventos existentes muestren su curva de subidas desde el día uno.
"""

from __future__ import annotations

import datetime as dt

import django.db.models.deletion
from django.db import migrations, models


def backfill_uploads(apps, schema_editor):
    Photo = apps.get_model("photos", "Photo")
    EventMetric = apps.get_model("events", "EventMetric")
    from django.db.models import Count
    from django.db.models.functions import TruncHour

    rows = (
        Photo.objects.exclude(status="deleted")
        .annotate(h=TruncHour("created_at", tzinfo=dt.timezone.utc))
        .values("event_id", "h")
        .annotate(c=Count("id"))
    )
    objs = [
        EventMetric(event_id=r["event_id"], metric="upload", bucket=r["h"], count=r["c"])
        for r in rows
        if r["h"] is not None
    ]
    EventMetric.objects.bulk_create(objs, ignore_conflicts=True, batch_size=1000)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0004_event_brand_overlay"),
        ("photos", "0005_photo_branded_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "metric",
                    models.CharField(
                        choices=[
                            ("view", "Vistas"),
                            ("search", "Búsquedas"),
                            ("download", "Descargas"),
                            ("upload", "Subidas"),
                        ],
                        max_length=16,
                        verbose_name="métrica",
                    ),
                ),
                ("bucket", models.DateTimeField(verbose_name="hora")),
                ("count", models.PositiveIntegerField(default=0, verbose_name="cantidad")),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metric_buckets",
                        to="events.event",
                    ),
                ),
            ],
            options={
                "verbose_name": "métrica de evento",
                "verbose_name_plural": "métricas de evento",
            },
        ),
        migrations.AddConstraint(
            model_name="eventmetric",
            constraint=models.UniqueConstraint(
                fields=("event", "metric", "bucket"), name="uniq_event_metric_bucket"
            ),
        ),
        migrations.RunPython(backfill_uploads, noop),
    ]
