"""Modelos `Photo`, `Bib`, `FaceEmbedding`.

- `Photo`: una imagen subida por un fotógrafo o por el admin.
- `Bib`: un dorsal detectado en una foto (puede haber 0..N por foto).
- `FaceEmbedding`: vector de 512 dims (InsightFace) para búsqueda por selfie.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pgvector.django import HnswIndex, VectorField

from apps.core.models import TimeStampedModel


# ---------------------------------------------------------------------------
# Photo
# ---------------------------------------------------------------------------
class PhotoStatus(models.TextChoices):
    UPLOADING = "uploading", _("Subiendo")
    PROCESSING = "processing", _("Procesando")
    PROCESSING_FAILED = "processing_failed", _("Falló el procesamiento")
    PENDING_REVIEW = "pending_review", _("Pendiente de revisión")
    APPROVED = "approved", _("Aprobada")
    REJECTED = "rejected", _("Rechazada")
    DELETED = "deleted", _("Borrada")


PRESIGNED_URL_DEFAULT_TTL = 15 * 60  # 15 minutos (CLAUDE.md §3 seguridad)


class Photo(TimeStampedModel):
    """Una foto subida al sistema."""

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="photos",
        verbose_name=_("evento"),
    )
    photographer_link = models.ForeignKey(
        "photographers.PhotographerLink",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="photos",
        verbose_name=_("link de fotógrafo"),
    )
    uploaded_by_admin = models.BooleanField(
        _("subida por admin"),
        default=False,
        help_text=_("Si True, fue subida por el super admin (no por un fotógrafo)."),
    )

    # --- R2 keys (paths de objetos en R2) ---
    original_key = models.CharField(_("key del original"), max_length=500, unique=True)
    preview_key = models.CharField(_("key del preview"), max_length=500, blank=True)
    thumbnail_key = models.CharField(_("key del thumbnail"), max_length=500, blank=True)

    # --- Metadata de imagen ---
    original_filename = models.CharField(_("nombre original"), max_length=255)
    width = models.PositiveIntegerField(_("ancho (px)"))
    height = models.PositiveIntegerField(_("alto (px)"))
    file_size = models.PositiveBigIntegerField(_("tamaño (bytes)"))

    # --- EXIF ---
    capture_time = models.DateTimeField(_("fecha de captura"), null=True, blank=True)
    camera_make = models.CharField(_("marca cámara"), max_length=100, blank=True)
    camera_model = models.CharField(_("modelo cámara"), max_length=100, blank=True)
    lens_model = models.CharField(_("lente"), max_length=200, blank=True)
    aperture = models.CharField(_("apertura"), max_length=20, blank=True)
    shutter_speed = models.CharField(_("velocidad obturador"), max_length=20, blank=True)
    iso = models.PositiveIntegerField(_("ISO"), null=True, blank=True)
    focal_length = models.CharField(_("focal"), max_length=20, blank=True)
    exif_raw = models.JSONField(_("EXIF crudo"), default=dict, blank=True)

    # --- Estado ---
    status = models.CharField(
        _("estado"),
        max_length=24,
        choices=PhotoStatus.choices,
        default=PhotoStatus.UPLOADING,
    )
    rejected_reason = models.CharField(_("motivo de rechazo"), max_length=255, blank=True)
    approved_at = models.DateTimeField(_("aprobada el"), null=True, blank=True)
    approved_by_admin = models.BooleanField(_("aprobada manualmente"), default=False)

    # --- Flags ML ---
    has_minors_detected = models.BooleanField(_("tiene menores detectados"), default=False)
    needs_minor_review = models.BooleanField(
        _("necesita revisión de menores"),
        default=False,
        help_text=_(
            "El estimador de edad detectó una cara dudosa (<22). El admin revisa "
            "en la cola de aprobación si hace falta blurear."
        ),
    )
    has_bibs_detected = models.BooleanField(_("tiene dorsales detectados"), default=False)
    has_faces_detected = models.BooleanField(_("tiene caras detectadas"), default=False)

    # --- Stats ---
    view_count = models.PositiveIntegerField(_("vistas"), default=0)
    download_count = models.PositiveIntegerField(_("descargas"), default=0)

    class Meta:
        verbose_name = _("foto")
        verbose_name_plural = _("fotos")
        ordering = ["-capture_time", "-created_at"]
        indexes = [
            models.Index(fields=["event", "status"], name="photo_event_status_idx"),
            models.Index(
                fields=["event", "status", "-capture_time"],
                name="photo_event_status_t_idx",
            ),
            models.Index(
                fields=["photographer_link", "status"],
                name="photo_link_status_idx",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Photo #{self.pk} of {self.event.name}"

    # --- URLs firmadas (R2) ---

    def get_preview_url(self, expires_in_seconds: int = PRESIGNED_URL_DEFAULT_TTL) -> str:
        """URL firmada al preview con watermark.

        En Fase 2 reemplazamos por boto3 con `generate_presigned_url`. Hoy
        devolvemos solo el key — útil para tests y desarrollo local.
        """
        return self._presign(self.preview_key, expires_in_seconds)

    def get_original_url(self, expires_in_seconds: int = PRESIGNED_URL_DEFAULT_TTL) -> str:
        """URL firmada al original (acceso restringido — solo descargas)."""
        return self._presign(self.original_key, expires_in_seconds)

    def get_thumbnail_url(self, expires_in_seconds: int = PRESIGNED_URL_DEFAULT_TTL) -> str:
        return self._presign(self.thumbnail_key, expires_in_seconds)

    def _presign(self, key: str, expires_in_seconds: int) -> str:
        """URL firmada de R2 (15 min default). Vacío si no hay key o R2 no está
        configurado (tests sin credentials)."""
        if not key:
            return ""
        from apps.photos.storage import R2NotConfiguredError, default_storage

        try:
            return default_storage().get_signed_url(key, expires_in=expires_in_seconds)
        except R2NotConfiguredError:
            return ""

    # --- Lifecycle ---

    def soft_delete(self) -> None:
        """Marca la foto como borrada sin tocar R2. El borrado físico lo hace
        la task de retención de Fase 6."""
        self.status = PhotoStatus.DELETED
        self.save(update_fields=["status", "updated_at"])

    def mark_approved(self, by_admin: bool = True) -> None:
        self.status = PhotoStatus.APPROVED
        self.approved_at = timezone.now()
        self.approved_by_admin = by_admin
        self.save(update_fields=["status", "approved_at", "approved_by_admin", "updated_at"])

    def increment_view_count(self) -> None:
        Photo.objects.filter(pk=self.pk).update(view_count=F("view_count") + 1)

    def increment_download_count(self) -> None:
        Photo.objects.filter(pk=self.pk).update(download_count=F("download_count") + 1)


# ---------------------------------------------------------------------------
# Bib
# ---------------------------------------------------------------------------
class BibSource(models.TextChoices):
    OCR_PADDLE = "ocr_paddle", _("OCR PaddleOCR")
    OCR_EASY = "ocr_easy", _("OCR EasyOCR")
    MANUAL_ADMIN = "manual_admin", _("Corregido por admin")
    MANUAL_USER_REPORT = "manual_user_report", _("Reportado por usuario")


class Bib(TimeStampedModel):
    """Un dorsal detectado/reportado en una foto."""

    photo = models.ForeignKey(
        Photo,
        on_delete=models.CASCADE,
        related_name="bibs",
        verbose_name=_("foto"),
    )
    number = models.CharField(
        _("número"),
        max_length=20,
        help_text=_("String — puede tener letras (ej. 'A123')."),
    )
    confidence = models.FloatField(
        _("confianza"),
        help_text=_("0.0 a 1.0 (1.0 si fue corregido manualmente)."),
    )
    source = models.CharField(_("origen"), max_length=24, choices=BibSource.choices)
    bbox = models.JSONField(
        _("bounding box"),
        default=dict,
        blank=True,
        help_text=_("Coordenadas en porcentaje de la imagen: {x, y, w, h}."),
    )
    is_validated = models.BooleanField(_("validado por admin"), default=False)
    rejected = models.BooleanField(
        _("rechazado"),
        default=False,
        help_text=_("Marcado como falso positivo."),
    )

    class Meta:
        verbose_name = _("dorsal")
        verbose_name_plural = _("dorsales")
        ordering = ["-confidence"]
        indexes = [
            models.Index(fields=["number"], name="bib_number_idx"),
            models.Index(fields=["photo", "number"], name="bib_photo_number_idx"),
            models.Index(
                fields=["photo", "is_validated", "rejected"],
                name="bib_validation_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["photo", "number", "source"],
                name="unique_bib_per_photo_source",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0.0) & models.Q(confidence__lte=1.0),
                name="bib_confidence_range",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Bib {self.number} on photo #{self.photo_id}"


# ---------------------------------------------------------------------------
# FaceEmbedding (pgvector)
# ---------------------------------------------------------------------------
class FaceEmbedding(TimeStampedModel):
    """Vector facial de 512 dimensiones (InsightFace buffalo_l)."""

    photo = models.ForeignKey(
        Photo,
        on_delete=models.CASCADE,
        related_name="face_embeddings",
        verbose_name=_("foto"),
    )
    embedding = VectorField(_("embedding"), dimensions=512)
    bbox = models.JSONField(
        _("bounding box"),
        default=dict,
        blank=True,
        help_text=_("{x, y, w, h} en porcentaje de la imagen."),
    )
    estimated_age = models.PositiveSmallIntegerField(
        _("edad estimada"),
        null=True,
        blank=True,
    )
    is_minor = models.BooleanField(
        _("es menor"),
        default=False,
        help_text=_("True si `estimated_age < 18`. Activa blur en preview público."),
    )

    # Para retention cleanup (CLAUDE.md §3 — 90 días sin match → borrar).
    last_matched_at = models.DateTimeField(_("último match"), null=True, blank=True)
    match_count = models.PositiveIntegerField(_("# de matches"), default=0)

    class Meta:
        verbose_name = _("embedding facial")
        verbose_name_plural = _("embeddings faciales")
        indexes = [
            # HNSW para similitud coseno (pgvector ≥0.5). Mejor recall que IVFFlat
            # para nuestros volúmenes proyectados (~180k vectores año 1).
            HnswIndex(
                name="face_embedding_hnsw_cos",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            models.Index(fields=["photo"], name="face_photo_idx"),
            models.Index(fields=["last_matched_at"], name="face_lastmatch_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"FaceEmbedding #{self.pk} on photo #{self.photo_id}"

    def record_match(self) -> None:
        """Llamar cuando este embedding fue parte de un match exitoso."""
        FaceEmbedding.objects.filter(pk=self.pk).update(
            last_matched_at=timezone.now(),
            match_count=F("match_count") + 1,
        )

    def _to_python_unused(self) -> Any:  # pragma: no cover - placeholder
        return None
