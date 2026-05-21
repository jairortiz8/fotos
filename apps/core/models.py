"""Modelos del app `core`: base + User custom + AuditLog + UserMFA."""

from __future__ import annotations

import ipaddress
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.fields import EncryptedCharField


# ---------------------------------------------------------------------------
# TimeStampedModel — mixin abstract para created_at / updated_at
# ---------------------------------------------------------------------------
class TimeStampedModel(models.Model):
    """Mixin abstract: agrega `created_at` y `updated_at` automáticos.

    Heredamos esto en TODOS los modelos del dominio.
    """

    created_at = models.DateTimeField(_("creado en"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# User custom (AbstractUser) — desde el día 1 (cambiar después es doloroso).
# ---------------------------------------------------------------------------
class User(AbstractUser):
    """Usuario del sistema. Hoy: solo el super admin (Jair).

    Extender campos acá cuando hagan falta sin romper migraciones.
    """

    # `date_joined` ya viene de AbstractUser; el alias created_at lo mantenemos
    # para consistencia con el resto del esquema.
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta(AbstractUser.Meta):
        verbose_name = _("usuario")  # type: ignore[assignment]
        verbose_name_plural = _("usuarios")  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# UserMFA — stub para activar TOTP en una fase posterior sin migration estructural.
# ---------------------------------------------------------------------------
class UserMFA(TimeStampedModel):
    """Datos de Multi-Factor Authentication por usuario.

    Hoy todos los registros tienen `totp_secret = NULL` e `is_active = False`.
    Cuando activemos MFA en una fase posterior, populamos `totp_secret` y
    flippeamos `is_active = True`.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa",
        verbose_name=_("usuario"),
    )
    totp_secret = EncryptedCharField(
        _("TOTP secret"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Encriptado con Fernet (clave derivada de SECRET_KEY)."),
    )
    backup_codes = models.JSONField(
        _("códigos de respaldo"),
        default=list,
        blank=True,
        help_text=_("Lista de hashes (no códigos en plano)."),
    )
    is_active = models.BooleanField(_("MFA activo"), default=False)
    activated_at = models.DateTimeField(_("activado el"), null=True, blank=True)

    class Meta:
        verbose_name = _("MFA de usuario")
        verbose_name_plural = _("MFA de usuarios")

    def __str__(self) -> str:  # pragma: no cover - trivial
        state = "activo" if self.is_active else "inactivo"
        return f"MFA {state} para {self.user}"


# ---------------------------------------------------------------------------
# AuditLog — registro append-only de acciones del admin / del sistema.
# ---------------------------------------------------------------------------
class AuditLog(TimeStampedModel):
    """Bitácora append-only.

    Acciones típicas (no exhaustivo):
    - `event.created`, `event.archived`, `event.deleted`
    - `photo.uploaded`, `photo.approved`, `photo.rejected`, `photo.deleted`
    - `photographer_link.generated`, `photographer_link.revoked`
    - `data.deletion_requested`, `data.deletion_completed`
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name=_("usuario"),
    )
    action = models.CharField(_("acción"), max_length=64, db_index=True)
    target_type = models.CharField(_("tipo de objeto"), max_length=64, blank=True)
    target_id = models.CharField(_("ID del objeto"), max_length=64, blank=True)
    metadata = models.JSONField(_("metadata"), default=dict, blank=True)
    ip_address = models.GenericIPAddressField(
        _("IP (anonimizada)"),
        null=True,
        blank=True,
        help_text=_("Para IPv4 anonimizamos el último octeto a 0."),
    )

    class Meta:
        verbose_name = _("evento de auditoría")
        verbose_name_plural = _("eventos de auditoría")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "-created_at"], name="audit_action_ts_idx"),
            models.Index(fields=["target_type", "target_id"], name="audit_target_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        who = self.user.username if self.user else "sistema"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {who} → {self.action}"

    # ----- API helpers -----

    @classmethod
    def log(
        cls,
        action: str,
        target: models.Model | None = None,
        *,
        user: User | None = None,
        metadata: dict[str, Any] | None = None,
        ip: str | None = None,
    ) -> AuditLog:
        """Crear un evento de auditoría.

        Anonimiza la IP automáticamente (último octeto a 0 en IPv4).
        """
        return cls.objects.create(
            user=user,
            action=action,
            target_type=target.__class__.__name__ if target is not None else "",
            target_id=str(target.pk) if target is not None and target.pk else "",
            metadata=metadata or {},
            ip_address=anonymize_ip(ip) if ip else None,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:  # noqa: DJ012
        # Defensa adicional: si alguien crea instancia directa con IP cruda.
        if self.ip_address:
            self.ip_address = anonymize_ip(self.ip_address) or self.ip_address
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def anonymize_ip(raw: str | None) -> str | None:
    """Anonimizar IP: zero last octet en IPv4, zero últimos 80 bits en IPv6."""
    if not raw:
        return None
    try:
        ip = ipaddress.ip_address(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(ip, ipaddress.IPv4Address):
        parts = str(ip).split(".")
        parts[-1] = "0"
        return ".".join(parts)
    # IPv6: dejamos solo los primeros 48 bits, ceros el resto.
    network = ipaddress.ip_network(f"{ip}/48", strict=False)
    return str(network.network_address)


def utc_now() -> Any:
    """Wrapper liviano sobre `timezone.now()` para reutilizar en migrations/tests."""
    return timezone.now()
