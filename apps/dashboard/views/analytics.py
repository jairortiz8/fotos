"""Analíticas del dashboard: curvas de descargas / vistas / búsquedas / subidas.

Los datos salen de `EventMetric` (contadores agregados por hora, sin PII). Las
curvas de descargas/vistas/búsquedas se llenan desde que se desplegó esta feature;
las subidas son históricas (backfill desde `Photo.created_at`).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils import timezone
from django.views.generic import TemplateView

from apps.dashboard.mixins import DashboardContextMixin
from apps.events.models import Event, EventMetric

ALLOWED_DAYS = (1, 7, 30, 90)
METRIC_KEYS = ("download", "view", "search", "upload")


def _default_event(events: list[Event]) -> Event | None:
    """Evento a mostrar por defecto: el de actividad más reciente, si no el primero."""
    if not events:
        return None
    latest_id = EventMetric.objects.order_by("-bucket").values_list("event_id", flat=True).first()
    if latest_id is not None:
        for e in events:
            if e.id == latest_id:
                return e
    return events[0]


def _build_charts(event_id: int | None, days: int) -> dict[str, Any]:
    """Arma las series por métrica, rellenando con cero los baldes sin datos."""
    now = timezone.now()
    start = now - dt.timedelta(days=days)
    hourly = days <= 2

    qs = EventMetric.objects.filter(bucket__gte=start)
    if event_id is not None:
        qs = qs.filter(event_id=event_id)
    rows = list(qs.values("metric", "bucket", "count"))

    local_now = timezone.localtime(now)

    # Claves ordenadas de los baldes (en hora de El Salvador) + su etiqueta.
    keys: list[Any] = []
    labels: dict[Any, str] = {}
    if hourly:
        cursor: Any = timezone.localtime(start).replace(minute=0, second=0, microsecond=0)
        stop: Any = local_now.replace(minute=0, second=0, microsecond=0)
        while cursor <= stop:
            keys.append(cursor)
            labels[cursor] = cursor.strftime("%Hh")
            cursor += dt.timedelta(hours=1)
    else:
        cursor = timezone.localtime(start).date()
        stop = local_now.date()
        while cursor <= stop:
            keys.append(cursor)
            labels[cursor] = cursor.strftime("%d/%m")
            cursor += dt.timedelta(days=1)
    now_key = keys[-1] if keys else None

    def key_for(bucket: dt.datetime) -> Any:
        loc = timezone.localtime(bucket)
        if hourly:
            return loc.replace(minute=0, second=0, microsecond=0)
        return loc.date()

    buckets: dict[str, dict[Any, int]] = {m: dict.fromkeys(keys, 0) for m in METRIC_KEYS}
    for r in rows:
        m = r["metric"]
        if m not in buckets:
            continue
        k = key_for(r["bucket"])
        if k in buckets[m]:
            buckets[m][k] += r["count"]

    charts = []
    for m in METRIC_KEYS:
        counts = [buckets[m][k] for k in keys]
        total = sum(counts)
        mx = max(counts) if counts else 0
        bars = [
            {
                "label": labels[k],
                "count": c,
                "pct": round(c / mx * 100) if mx else 0,
                "is_now": k == now_key,
            }
            for k, c in zip(keys, counts, strict=True)
        ]
        charts.append({"key": m, "total": total, "max": mx, "bars": bars})

    return {"charts": charts, "granularity": "hour" if hourly else "day"}


class AnalyticsView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/analytics.html"
    active_nav = "analytics"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)

        try:
            days = int(self.request.GET.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        if days not in ALLOWED_DAYS:
            days = 7

        events = list(Event.objects.order_by("-date", "-created_at"))

        raw = self.request.GET.get("event", "")
        selected: Event | None = None
        if raw == "all":
            selected = None
        elif raw:
            try:
                wanted = int(raw)
            except (TypeError, ValueError):
                wanted = None
            if wanted is not None:
                selected = next((e for e in events if e.id == wanted), None)
        else:
            selected = _default_event(events)

        # Agregamos "todos los eventos" cuando el usuario lo pide (raw=="all") o
        # cuando no hay un evento válido seleccionado.
        event_id = None if selected is None else selected.id
        data = _build_charts(event_id, days)

        ctx.update(
            {
                "days": days,
                "days_options": ALLOWED_DAYS,
                "events": events,
                "selected_event": selected,
                "is_all": selected is None,
                "event_param": "all" if selected is None else str(selected.id),
                "charts": data["charts"],
                "granularity": data["granularity"],
            }
        )
        return ctx
