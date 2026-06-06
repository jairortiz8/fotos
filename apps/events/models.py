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
