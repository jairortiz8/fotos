"""Modelo `ZipDownload` — un pedido de descarga ZIP de fotos seleccionadas.

El ZIP se genera async (Celery), se sube a R2, y se sirve por URL firmada con
vigencia corta (1h). Un cron borra los expirados de R2.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class ZipStatus(models.TextChoices):
    PENDING = "pending", _("Pendiente")
    PROCESSING = "processing", _("Procesando")
    READY = "ready", _("Lista")
    FAILED = "failed", _("Falló")
    EXPIRED = "expired", _("Expirada")


MAX_PHOTOS_PER_ZIP = 200


class ZipDownload(TimeStampedModel):
    """Pedido de descarga ZIP. `photo_ids` son los IDs seleccionados."""

    requester_ip_hash = models.CharField(
        _("hash de IP solicitante"),
        max_length=64,
        help_text=_("sha256 — sin guardar la IP cruda."),
    )
    photo_ids = models.JSONField(_("IDs de fotos"), default=list)
    photo_count = models.PositiveIntegerField(_("cantidad de fotos"), default=0)
    total_size_mb = models.FloatField(_("tamaño total (MB)"), default=0.0)

    status = models.CharField(
        _("estado"),
        max_length=16,
        choices=ZipStatus.choices,
        default=ZipStatus.PENDING,
    )
    zip_key = models.CharField(_("key del ZIP en R2"), max_length=500, blank=True)
    download_url = models.URLField(_("URL firmada"), max_length=1000, blank=True)
    expires_at = models.DateTimeField(_("expira el"), null=True, blank=True)

    download_count = models.PositiveIntegerField(_("descargas"), default=0)
    error_message = models.TextField(_("mensaje de error"), blank=True)

    class Meta:
        verbose_name = _("descarga ZIP")
        verbose_name_plural = _("descargas ZIP")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"], name="zip_status_exp_idx"),
            models.Index(fields=["requester_ip_hash"], name="zip_iphash_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"ZipDownload #{self.pk} ({self.status}, {self.photo_count} fotos)"
