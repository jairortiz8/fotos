"""Modelo `Event` — una carrera específica.

Implementa la política de retención escalonada de CLAUDE.md §3 y ADR 0003.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class EventStatus(models.TextChoices):
    """Estados del ciclo de vida de un evento.

    Transiciones esperadas (típicas, no únicas):
        draft → upcoming → live → public_closed →
        searchable_only → archived → pending_deletion → deleted
    """

    DRAFT = "draft", _("Borrador")
    UPCOMING = "upcoming", _("Próximo")
    LIVE = "live", _("Galería abierta")
    PUBLIC_CLOSED = "public_closed", _("Galería cerrada")
    SEARCHABLE_ONLY = "searchable_only", _("Sólo búsqueda")
    ARCHIVED = "archived", _("Archivado")
    PENDING_DELETION = "pending_deletion", _("Pendiente de borrado")
    DELETED = "deleted", _("Borrado")


class EventVisibility(models.TextChoices):
    PUBLIC = "public", _("Público — listado en home")
    UNLISTED = "unlisted", _("No listado — accesible por URL")
    PRIVATE = "private", _("Privado — solo admin")


class BrandOverlay(models.TextChoices):
    """Template de logos de marca a pegar en las fotos del evento.

    El valor apunta a un template definido en `apps.photos.overlays.TEMPLATES`.
    Vacío = sin logos (comportamiento normal con watermark diagonal).
    """

    NONE = "", _("Ninguno (watermark normal)")
    SURF_CITY = "surf_city", _("Surf City (logos en las esquinas)")
    SEPTIMO_CEP = "septimo_cep", _("SÉPTIMO x CEP (5 logos abajo)")


# Defaults de retención (configurables por evento).
DEFAULT_PUBLIC_DAYS = 90
DEFAULT_SEARCHABLE_DAYS = 180
DEFAULT_ARCHIVE_DAYS = 365


class Event(TimeStampedModel):
    """Una carrera de la cual subimos y publicamos fotos."""

    name = models.CharField(_("nombre"), max_length=255)
    slug = models.SlugField(_("slug"), max_length=255, unique=True)
    date = models.DateField(_("fecha del evento"))
    location = models.CharField(_("ubicación"), max_length=255, blank=True)
    description = models.TextField(_("descripción"), blank=True)
    cover_image = models.ImageField(
        _("imagen de portada"),
        upload_to="event_covers/",
        blank=True,
        null=True,
    )
    # Key de R2 de la portada (webp). El ImageField de arriba quedó obsoleto:
    # iba al disco LOCAL, que en Railway es efímero y no se sirve → la portada
    # "se guardaba pero no se mostraba". La portada real vive en R2 bajo esta key
    # y se sirve por `EventCoverView`. (cover_image se mantiene dormido para no
    # hacer una migración destructiva; se puede dropear más adelante.)
    cover_key = models.CharField(_("portada (R2)"), max_length=255, blank=True, default="")

    # --- Organizador (opcional, por evento) ---
    organizer_name = models.CharField(_("organizador"), max_length=120, blank=True, default="")
    organizer_instagram = models.CharField(
        _("Instagram del organizador"),
        max_length=200,
        blank=True,
        default="",
        help_text=_("Usuario (@evento) o link completo."),
    )
    organizer_facebook = models.CharField(
        _("Facebook del organizador"),
        max_length=200,
        blank=True,
        default="",
        help_text=_("Usuario o link completo de la página."),
    )

    status = models.CharField(
        _("estado"),
        max_length=32,
        choices=EventStatus.choices,
        default=EventStatus.DRAFT,
    )
    visibility = models.CharField(
        _("visibilidad"),
        max_length=16,
        choices=EventVisibility.choices,
        default=EventVisibility.PUBLIC,
    )
    brand_overlay = models.CharField(
        _("logos de marca en las fotos"),
        max_length=32,
        choices=BrandOverlay.choices,
        blank=True,
        default="",
        help_text=_(
            "Pega los logos del evento en las esquinas de abajo de cada foto. "
            "Se aplica SOLO a este evento."
        ),
    )

    # Expone este evento en el área de invitados (`/invitados/`) para que los
    # community managers descarguen los originales limpios. Default False: un
    # evento nuevo NO aparece para invitados hasta que se prende explícitamente.
    reviewer_visible = models.BooleanField(
        _("visible para invitados"),
        default=False,
        help_text=_(
            "Si está activado, los invitados ven este evento y bajan sus originales sin logos."
        ),
    )

    # --- Política de retención (configurable por evento, defaults en save()) ---
    public_until = models.DateTimeField(
        _("público hasta"),
        null=True,
        blank=True,
        help_text=_("Después de esta fecha la galería pública se cierra."),
    )
    searchable_until = models.DateTimeField(
        _("búsquedas habilitadas hasta"),
        null=True,
        blank=True,
        help_text=_("Después de esta fecha solo el admin puede buscar."),
    )
    archive_until = models.DateTimeField(
        _("archivado hasta"),
        null=True,
        blank=True,
        help_text=_("Después de esta fecha el evento se borra (R2 + DB)."),
    )
    permanent_archive = models.BooleanField(
        _("archivo permanente"),
        default=False,
        help_text=_(
            "Si está activado, el evento NUNCA cambia de estado por retención. "
            "Para organizadores que pagan por archivo permanente."
        ),
    )

    # --- Stats denormalizadas (actualizadas por signals / tasks en fases posteriores) ---
    photo_count = models.PositiveIntegerField(_("fotos totales"), default=0)
    pending_count = models.PositiveIntegerField(_("fotos pendientes"), default=0)
    photographer_count = models.PositiveIntegerField(_("fotógrafos"), default=0)
    search_count = models.PositiveIntegerField(_("búsquedas realizadas"), default=0)
    download_count = models.PositiveIntegerField(_("descargas de ZIP"), default=0)

    class Meta:
        verbose_name = _("evento")
        verbose_name_plural = _("eventos")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["status", "-date"], name="event_status_date_idx"),
            models.Index(fields=["visibility", "status"], name="event_vis_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.date:%Y-%m-%d})"

    # --- Lifecycle ---

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.slug:
            self.slug = self._unique_slug_from_name()
        if self.date:
            base = dt.datetime.combine(self.date, dt.time.max).replace(tzinfo=dt.UTC)
            if not self.public_until:
                self.public_until = base + dt.timedelta(days=DEFAULT_PUBLIC_DAYS)
            if not self.searchable_until:
                self.searchable_until = base + dt.timedelta(days=DEFAULT_SEARCHABLE_DAYS)
            if not self.archive_until:
                self.archive_until = base + dt.timedelta(days=DEFAULT_ARCHIVE_DAYS)
        super().save(*args, **kwargs)

    def _unique_slug_from_name(self) -> str:
        base = slugify(self.name) or "evento"
        slug = base
        idx = 2
        while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{idx}"
            idx += 1
        return slug

    # --- URLs ---

    def get_absolute_url(self) -> str:
        # La URL real se define en Fase 3 (galería pública). Por ahora apunta
        # al admin para no romper.
        try:
            return reverse("admin:events_event_change", args=[self.pk])
        except Exception:
            return f"/admin/events/event/{self.pk}/change/"

    def cover_url(self) -> str:
        """URL (relativa) de la portada, o "" si no hay. La sirve `EventCoverView`
        desde R2 con cache — URL estable y cacheable (a diferencia de una URL
        firmada que expira y no se cachea). Lleva `?v=<updated_at>` para invalidar
        el cache cuando se cambia la portada."""
        if not self.cover_key:
            return ""
        url = reverse("events:cover", kwargs={"slug": self.slug})
        if self.updated_at:
            return f"{url}?v={int(self.updated_at.timestamp())}"
        return url

    # --- Redes del organizador ---

    def instagram_url(self) -> str:
        return _social_url(self.organizer_instagram, "instagram.com")

    def facebook_url(self) -> str:
        return _social_url(self.organizer_facebook, "facebook.com")

    def has_organizer(self) -> bool:
        return bool(self.organizer_name or self.organizer_instagram or self.organizer_facebook)

    # --- Estado derivado de la política de retención ---

    def is_public(self) -> bool:
        """¿La galería pública está activa hoy?"""
        if self.permanent_archive:
            return self.status in {EventStatus.LIVE, EventStatus.PUBLIC_CLOSED}
        if self.status not in {EventStatus.LIVE, EventStatus.PUBLIC_CLOSED}:
            return False
        return not (self.public_until and timezone.now() > self.public_until)

    def is_searchable(self) -> bool:
        """¿Se pueden hacer búsquedas (dorsal/selfie) por el público?"""
        if self.permanent_archive:
            return self.status != EventStatus.DELETED
        if self.status in {
            EventStatus.DRAFT,
            EventStatus.ARCHIVED,
            EventStatus.PENDING_DELETION,
            EventStatus.DELETED,
        }:
            return False
        return not (self.searchable_until and timezone.now() > self.searchable_until)

    def is_archived(self) -> bool:
        return self.status in {EventStatus.ARCHIVED, EventStatus.PENDING_DELETION}

    def days_until_archive(self) -> int | None:
        if not self.archive_until or self.permanent_archive:
            return None
        delta = self.archive_until - timezone.now()
        return max(delta.days, 0)


def _social_url(value: str, domain: str) -> str:
    """Normaliza un campo de red social a una URL completa.

    Acepta un link completo (`https://instagram.com/evento`) tal cual, o un
    usuario (`@evento` / `evento`) y arma `https://<domain>/<usuario>`. Devuelve
    "" si está vacío.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    handle = value.lstrip("@").strip("/")
    return f"https://{domain}/{handle}"


class EventMetric(models.Model):
    """Contador AGREGADO por hora, por evento y tipo de métrica.

    Sirve para dibujar curvas (descargas/vistas/búsquedas/subidas por día/hora)
    en el dashboard SIN romper la línea de privacidad del proyecto (CLAUDE.md §3):
    NO guardamos un registro por evento individual — sin IP, sin qué se buscó, sin
    quién. Es el MISMO contador denormalizado de siempre (`Event.download_count`,
    `Photo.view_count`, …) pero partido en baldes de una hora. Cero PII.

    `bucket` es el inicio de la hora en UTC (tz-aware). El dashboard lo convierte
    a hora de El Salvador para mostrar.
    """

    class Metric(models.TextChoices):
        VIEW = "view", _("Vistas")
        SEARCH = "search", _("Búsquedas")
        DOWNLOAD = "download", _("Descargas")
        UPLOAD = "upload", _("Subidas")

    event = models.ForeignKey(
        "events.Event", on_delete=models.CASCADE, related_name="metric_buckets"
    )
    metric = models.CharField(_("métrica"), max_length=16, choices=Metric.choices)
    bucket = models.DateTimeField(_("hora"))
    count = models.PositiveIntegerField(_("cantidad"), default=0)

    class Meta:
        verbose_name = _("métrica de evento")
        verbose_name_plural = _("métricas de evento")
        # El UniqueConstraint (event, metric, bucket) ya crea el índice que usan
        # todas las consultas (filtrar por evento+métrica y rango de `bucket`),
        # así que no agregamos un Index aparte.
        constraints = [
            models.UniqueConstraint(
                fields=["event", "metric", "bucket"], name="uniq_event_metric_bucket"
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_id}/{self.metric}@{self.bucket:%Y-%m-%d %H}:00 = {self.count}"
