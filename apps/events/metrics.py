"""Registro y consulta de métricas agregadas por hora (curvas del dashboard).

PRIVACIDAD (CLAUDE.md §3): sólo contadores agregados por (evento, métrica, hora).
Nunca IP, nunca el contenido de una búsqueda, nunca por-usuario. Es el contador
denormalizado de siempre, partido en baldes de una hora para poder graficar.

`record_event_metric` es instrumentación: NUNCA debe tumbar el request del
usuario. Cualquier error se traga y se loguea a debug.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.events.models import EventMetric

logger = logging.getLogger(__name__)

Metric = EventMetric.Metric


def _hour_bucket(when: dt.datetime) -> dt.datetime:
    """Trunca un datetime tz-aware al inicio de su hora (en UTC)."""
    when = when.astimezone(dt.UTC)
    return when.replace(minute=0, second=0, microsecond=0)


def record_event_metric(
    event_id: int | None,
    metric: str,
    count: int = 1,
    when: dt.datetime | None = None,
) -> None:
    """Suma `count` al balde de la hora actual para (evento, métrica).

    Race-safe: primero intenta UPDATE; si el balde no existía, INSERT; si dos
    requests insertan a la vez, el IntegrityError vuelve a caer al UPDATE. Todo
    dentro de un savepoint para no envenenar una transacción externa.
    """
    if not event_id or count == 0:
        return
    bucket = _hour_bucket(when or timezone.now())
    try:
        updated = EventMetric.objects.filter(
            event_id=event_id, metric=metric, bucket=bucket
        ).update(count=F("count") + count)
        if updated:
            return
        try:
            with transaction.atomic():
                EventMetric.objects.create(
                    event_id=event_id, metric=metric, bucket=bucket, count=count
                )
        except IntegrityError:
            EventMetric.objects.filter(
                event_id=event_id, metric=metric, bucket=bucket
            ).update(count=F("count") + count)
    except Exception:  # la instrumentación jamás rompe el request del usuario
        logger.debug(
            "record_event_metric falló (event=%s metric=%s)", event_id, metric, exc_info=True
        )
