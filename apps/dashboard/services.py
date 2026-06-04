"""Servicios del dashboard: counters, stats, QR y mensajes.

Estos helpers son SÍNCRONOS a propósito. Recalcular los counters denormalizados
de `Event` es barato (un par de COUNTs) y no depende del worker de Celery — que
hoy no corre en prod (CLAUDE.md, pendiente Fase 2+). Las stats se derivan SOLO de
datos ya existentes (sin `SearchLog`, decisión de privacidad de Fase 3).
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.events.models import Event, EventStatus
from apps.photographers.models import PhotographerLink
from apps.photos.models import Photo, PhotoStatus

# Estados que NO cuentan como "foto real" del evento (todavía procesándose o muerta).
_NON_PHOTO_STATUSES = [
    PhotoStatus.UPLOADING,
    PhotoStatus.PROCESSING,
    PhotoStatus.PROCESSING_FAILED,
    PhotoStatus.DELETED,
]


# ---------------------------------------------------------------------------
# Counters denormalizados de Event
# ---------------------------------------------------------------------------
def recalculate_event_counters(event: Event) -> Event:
    """Recalcula y guarda los counters denormalizados de un evento.

    Llamar después de aprobar/rechazar/borrar fotos o generar/revocar links.
    Síncrono y barato; no usa Celery.
    """
    photos = Photo.objects.filter(event=event)
    event.photo_count = photos.exclude(status__in=_NON_PHOTO_STATUSES).count()
    event.pending_count = photos.filter(status=PhotoStatus.PENDING_REVIEW).count()
    event.photographer_count = PhotographerLink.objects.filter(event=event).count()
    event.save(update_fields=["photo_count", "pending_count", "photographer_count", "updated_at"])
    return event


# ---------------------------------------------------------------------------
# Stats del dashboard home
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DashboardStats:
    total_events: int
    events_this_month: int
    total_photos: int
    photos_this_week: int
    storage_used_gb: float
    pending_photos: int
    searches_total: int
    downloads_total: int


def dashboard_stats() -> DashboardStats:
    """Métricas globales para las stat cards del home. Sólo datos existentes."""
    now = timezone.now()
    last_week = now - timedelta(days=7)
    last_month = now - timedelta(days=30)

    events = Event.objects.exclude(status=EventStatus.DELETED)
    photos = Photo.objects.exclude(status=PhotoStatus.DELETED)

    storage_bytes = photos.aggregate(total=Sum("file_size"))["total"] or 0
    search_total = events.aggregate(total=Sum("search_count"))["total"] or 0
    download_total = events.aggregate(total=Sum("download_count"))["total"] or 0

    return DashboardStats(
        total_events=events.count(),
        events_this_month=events.filter(created_at__gte=last_month).count(),
        total_photos=photos.count(),
        photos_this_week=photos.filter(created_at__gte=last_week).count(),
        storage_used_gb=round(storage_bytes / (1024**3), 1),
        pending_photos=photos.filter(status=PhotoStatus.PENDING_REVIEW).count(),
        searches_total=int(search_total),
        downloads_total=int(download_total),
    )


def uploads_by_hour_today() -> list[int]:
    """Devuelve 24 enteros: # de fotos subidas en cada hora de HOY (00..23)."""
    today = timezone.localdate()
    buckets = [0] * 24
    qs = (
        Photo.objects.exclude(status=PhotoStatus.DELETED)
        .filter(created_at__date=today)
        .values_list("created_at", flat=True)
    )
    for created in qs:
        local = timezone.localtime(created)
        buckets[local.hour] += 1
    return buckets


@dataclass(frozen=True)
class PendingSummary:
    count: int
    avg_age_label: str  # ej. "3h 12m" o "—"
    sample_photos: list[Photo]


def pending_summary(limit: int = 5) -> PendingSummary:
    """Resumen de la cola de aprobación para la card del home."""
    qs = Photo.objects.filter(status=PhotoStatus.PENDING_REVIEW).order_by("created_at")
    count = qs.count()
    sample = list(qs[:limit])

    if count:
        now = timezone.now()
        oldest = qs.first()
        # Antigüedad promedio aproximada con el promedio de created_at.
        total_seconds = sum((now - p.created_at).total_seconds() for p in qs[:200])
        avg_seconds = total_seconds / min(count, 200)
        avg_age_label = _humanize_duration(avg_seconds)
        if oldest is None:  # pragma: no cover - defensivo
            avg_age_label = "—"
    else:
        avg_age_label = "—"

    return PendingSummary(count=count, avg_age_label=avg_age_label, sample_photos=sample)


def _humanize_duration(seconds: float) -> str:
    """'3h 12m' / '45m' / '2d 4h'."""
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


# ---------------------------------------------------------------------------
# Stats page (charts derivados de datos existentes)
# ---------------------------------------------------------------------------
def uploads_by_day(days: int = 30) -> list[tuple[date, int]]:
    """Fotos subidas por día en la ventana dada (orden ascendente)."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    counts: dict[date, int] = {start + timedelta(days=i): 0 for i in range(days)}
    qs = (
        Photo.objects.exclude(status=PhotoStatus.DELETED)
        .filter(created_at__date__gte=start)
        .values_list("created_at", flat=True)
    )
    for created in qs:
        d = timezone.localtime(created).date()
        if d in counts:
            counts[d] += 1
    return sorted(counts.items())


def top_events_by_photos(limit: int = 10) -> list[Event]:
    """Top eventos por cantidad de fotos aprobadas."""
    return list(
        Event.objects.exclude(status=EventStatus.DELETED)
        .annotate(approved=Count("photos", filter=Q(photos__status=PhotoStatus.APPROVED)))
        .order_by("-approved")[:limit]
    )


def status_distribution() -> dict[str, int]:
    """Conteo de fotos por estado (para un donut/barras)."""
    rows = Photo.objects.values("status").annotate(n=Count("id")).order_by()
    return {row["status"]: row["n"] for row in rows}


# ---------------------------------------------------------------------------
# QR + mensaje de WhatsApp para links de fotógrafo
# ---------------------------------------------------------------------------
def make_qr_png_data_uri(data: str) -> str:
    """Genera un QR PNG y lo devuelve como data URI base64 (para <img> inline)."""
    import qrcode

    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def whatsapp_message(*, name: str, event_name: str, url: str, expires_label: str) -> str:
    """Mensaje pre-armado para copiar y mandar por WhatsApp al fotógrafo."""
    return (
        f"Hola {name}, te paso el link para subir las fotos del {event_name}: {url}\n\n"
        f"Link válido hasta {expires_label}. Cualquier consulta avisame."
    )


# ---------------------------------------------------------------------------
# Estado de un link de fotógrafo (para listados)
# ---------------------------------------------------------------------------
def link_status(link: PhotographerLink) -> tuple[str, str]:
    """(tono, etiqueta) del estado de un link: revocado / expirado / activo."""
    from django.utils.translation import gettext as _

    if not link.is_active:
        return ("red", _("Revocado"))
    if link.expires_at < timezone.now():
        return ("neutral", _("Expirado"))
    return ("green", _("Activo"))


def annotate_link_statuses(links: list[PhotographerLink]) -> list[PhotographerLink]:
    for link in links:
        link.status_tone, link.status_label = link_status(link)  # type: ignore[attr-defined]
    return links
