"""Modelo `DataDeletionRequest` — log de los borrados solicitados por usuarios.

Cuando un corredor sube su selfie a `/privacy/delete-my-data`, se crea uno
de estos registros. NO guardamos el embedding permanentemente — sólo el
hash de la IP para rate-limiting sin guardar la IP cruda.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class DeletionStatus(models.TextChoices):
    PENDING = "pending", _("Pendiente")
    PROCESSING = "processing", _("Procesando")
    COMPLETED = "completed", _("Completada")
    FAILED = "failed", _("Falló")


class DataDeletionRequest(TimeStampedModel):
    """Una solicitud de borrado por usuario."""

    matched_photo_count = models.PositiveIntegerField(_("fotos encontradas"), default=0)
    deleted_photo_count = models.PositiveIntegerField(_("fotos borradas"), default=0)
    deleted_embedding_count = models.PositiveIntegerField(
        _("embeddings borrados"),
        default=0,
    )

    status = models.CharField(
        _("estado"),
        max_length=16,
        choices=DeletionStatus.choices,
        default=DeletionStatus.PENDING,
    )
    requester_ip_hash = models.CharField(
        _("hash de IP solicitante (sha256)"),
        max_length=64,
        help_text=_("Para rate-limiting sin guardar IP cruda."),
    )

    completed_at = models.DateTimeField(_("completada el"), null=True, blank=True)
    error_message = models.TextField(_("mensaje de error"), blank=True)

    class Meta:
        verbose_name = _("solicitud de borrado de datos")
        verbose_name_plural = _("solicitudes de borrado de datos")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="del_status_ts_idx"),
            models.Index(fields=["requester_ip_hash"], name="del_iphash_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Borrado #{self.pk} ({self.status})"
