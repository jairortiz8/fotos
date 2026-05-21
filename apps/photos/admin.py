"""Admin de Photo + Bib + FaceEmbedding."""

from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from apps.photos.models import Bib, FaceEmbedding, Photo, PhotoStatus


class BibInline(TabularInline):
    model = Bib
    extra = 0
    fields = ("number", "confidence", "source", "is_validated", "rejected")
    readonly_fields = ("source",)
    tab = True


class FaceEmbeddingInline(TabularInline):
    model = FaceEmbedding
    extra = 0
    fields = ("estimated_age", "is_minor", "last_matched_at", "match_count")
    readonly_fields = ("estimated_age", "is_minor", "last_matched_at", "match_count")
    can_delete = False
    tab = True


@admin.register(Photo)
class PhotoAdmin(ModelAdmin):
    list_display = (
        "id",
        "event",
        "status_pill",
        "bibs_summary",
        "has_minors_detected",
        "capture_time",
        "uploaded_by_admin",
    )
    list_filter = (
        "status",
        "event",
        "has_minors_detected",
        "has_bibs_detected",
        "uploaded_by_admin",
    )
    search_fields = ("original_filename", "original_key", "event__name", "bibs__number")
    readonly_fields = (
        "original_key",
        "preview_key",
        "thumbnail_key",
        "width",
        "height",
        "file_size",
        "capture_time",
        "camera_make",
        "camera_model",
        "lens_model",
        "aperture",
        "shutter_speed",
        "iso",
        "focal_length",
        "exif_raw",
        "view_count",
        "download_count",
        "approved_at",
        "created_at",
        "updated_at",
    )
    inlines = (BibInline, FaceEmbeddingInline)
    date_hierarchy = "capture_time"

    @admin.display(description=_("estado"), ordering="status")
    def status_pill(self, obj: Photo) -> str:
        colors: dict[str, str] = {
            PhotoStatus.UPLOADING.value: "#6B6B70",
            PhotoStatus.PROCESSING.value: "#00D4FF",
            PhotoStatus.PENDING_REVIEW.value: "#F59E0B",
            PhotoStatus.APPROVED.value: "#10B981",
            PhotoStatus.REJECTED.value: "#EF4444",
            PhotoStatus.DELETED.value: "#EF4444",
        }
        c = colors.get(obj.status, "#A1A1A6")
        return format_html(
            '<span style="display:inline-flex;padding:4px 10px;border-radius:999px;'
            "background:{}1A;color:{};border:1px solid {}40;font-size:11px;"
            'text-transform:uppercase;letter-spacing:0.04em;">{}</span>',
            c,
            c,
            c,
            obj.get_status_display(),
        )

    @admin.display(description=_("dorsales"))
    def bibs_summary(self, obj: Photo) -> str:
        bibs = obj.bibs.all()[:5]
        if not bibs:
            return "—"
        return ", ".join(b.number for b in bibs)


@admin.register(Bib)
class BibAdmin(ModelAdmin):
    list_display = (
        "number",
        "photo",
        "source",
        "confidence",
        "is_validated",
        "rejected",
    )
    list_filter = ("source", "is_validated", "rejected")
    search_fields = ("number", "photo__original_filename")
    readonly_fields = ("photo", "confidence", "source", "bbox", "created_at", "updated_at")


@admin.register(FaceEmbedding)
class FaceEmbeddingAdmin(ModelAdmin):
    """Sólo lectura: los embeddings se crean exclusivamente desde el pipeline ML."""

    list_display = (
        "id",
        "photo",
        "estimated_age",
        "is_minor",
        "last_matched_at",
        "match_count",
    )
    list_filter = ("is_minor",)
    search_fields = ("photo__original_filename",)
    readonly_fields = (
        "photo",
        "embedding",
        "bbox",
        "estimated_age",
        "is_minor",
        "last_matched_at",
        "match_count",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False
