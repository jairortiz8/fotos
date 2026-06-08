"""Modelo `PhotographerLink` — token URL único por fotógrafo+evento.

Tokens:
- Token plano de 32 chars URL-safe (`secrets.token_urlsafe(24)`).
- NUNCA guardado en plano: en DB vive `sha256(token).hexdigest()`.
- El plano sólo se ve UNA vez en `generate_token_and_create()`. Después
  el admin tiene que regenerar si lo perdió.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from typing import TYPE_CHECKING, Any

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, anonymize_ip

if TYPE_CHECKING:
    from apps.events.models import Event


DEFAULT_EXPIRY_DAYS = 30  # 30 días después de la fecha del evento


class PhotographerLink(TimeStampedModel):
    """Link de upload temporal para un fotógrafo."""

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="photographer_links",
        verbose_name=_("evento"),
    )
    photographer_name = models.CharField(_("nombre"), max_length=255)
    photographer_email = models.EmailField(_("email"), blank=True, null=True)  # noqa: DJ001
    photographer_phone = models.CharField(
        _("teléfono"),
        max_length=20,
        blank=True,
        help_text=_("Para mandar el link por WhatsApp."),
    )

    # --- Token ---
    token_hash = models.CharField(
        _("hash del token (sha256)"),
        max_length=64,
        unique=True,
        db_index=True,
    )

    # --- Vigencia ---
    expires_at = models.DateTimeField(_("expira el"))
    is_active = models.BooleanField(_("activo"), default=True)
    revoked_at = models.DateTimeField(_("revocado el"), null=True, blank=True)
    revoked_reason = models.CharField(
        _("motivo de revocación"),
        max_length=255,
        blank=True,
    )

    # --- Límites ---
    photo_limit = models.PositiveIntegerField(
        _("límite de fotos"),
        null=True,
        blank=True,
        help_text=_("Nulo = sin límite."),
    )

    # --- Contadores y uso ---
    photos_uploaded = models.PositiveIntegerField(_("fotos subidas"), default=0)
    last_used_at = models.DateTimeField(_("último uso"), null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(
        _("última IP usada (anonimizada)"),
        null=True,
        blank=True,
    )
    # Imagen destacada de la "carpeta" del fotógrafo (R2, webp). La sube el
    # fotógrafo desde su portal. Se sirve por `PhotographerCoverView`.
    featured_image_key = models.CharField(
        _("imagen destacada (R2)"), max_length=255, blank=True, default=""
    )

    class Meta:
        verbose_name = _("link de fotógrafo")
        verbose_name_plural = _("links de fotógrafos")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event", "is_active"], name="link_event_active_idx"),
            models.Index(fields=["expires_at", "is_active"], name="link_exp_active_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.photographer_name} → {self.event.name}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.last_used_ip:
            self.last_used_ip = anonymize_ip(self.last_used_ip) or self.last_used_ip
        super().save(*args, **kwargs)

    def featured_url(self) -> str:
        """URL (relativa) de la imagen destacada de la carpeta, o "" si no hay.
        La sirve `PhotographerCoverView` desde R2; versionada para bustear cache."""
        if not self.featured_image_key:
            return ""
        from django.urls import reverse

        url = reverse("photographer:cover", kwargs={"link_id": self.id})
        if self.updated_at:
            return f"{url}?v={int(self.updated_at.timestamp())}"
        return url

    # --- API ---

    @classmethod
    def generate_token_and_create(
        cls,
        event: Event,
        name: str,
        *,
        email: str | None = None,
        phone: str = "",
        expires_in_days: int | None = None,
        photo_limit: int | None = None,
    ) -> tuple[PhotographerLink, str]:
        """Crear un link nuevo y devolver `(instance, token_plano)`.

        El token plano se devuelve **una sola vez** — después solo queda el hash
        en DB. Si el admin lo pierde tiene que regenerar.
        """
        raw_token = secrets.token_urlsafe(24)
        token_hash = _hash_token(raw_token)

        days = expires_in_days if expires_in_days is not None else DEFAULT_EXPIRY_DAYS
        base = dt.datetime.combine(event.date, dt.time.max).replace(tzinfo=dt.UTC)
        expires_at = base + dt.timedelta(days=days)

        instance = cls.objects.create(
            event=event,
            photographer_name=name,
            photographer_email=email,
            photographer_phone=phone,
            token_hash=token_hash,
            expires_at=expires_at,
            photo_limit=photo_limit,
        )
        return instance, raw_token

    def verify_token(self, raw_token: str) -> bool:
        """Comparación constante-en-tiempo del hash del token."""
        if not raw_token:
            return False
        return secrets.compare_digest(_hash_token(raw_token), self.token_hash)

    def is_valid(self) -> bool:
        """¿El link sigue siendo usable hoy?"""
        if not self.is_active or self.revoked_at is not None:
            return False
        if self.expires_at <= timezone.now():
            return False
        return not (self.photo_limit is not None and self.photos_uploaded >= self.photo_limit)

    def revoke(self, reason: str = "") -> None:
        """Revocar manualmente. Logueado en AuditLog."""
        from apps.core.models import AuditLog  # import local para evitar cycles

        self.is_active = False
        self.revoked_at = timezone.now()
        self.revoked_reason = reason
        self.save(update_fields=["is_active", "revoked_at", "revoked_reason", "updated_at"])
        AuditLog.log(
            "photographer_link.revoked",
            target=self,
            metadata={"reason": reason, "event_id": self.event_id},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
