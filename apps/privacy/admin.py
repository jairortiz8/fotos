"""Admin de privacidad — DataDeletionRequest sólo lectura."""

from __future__ import annotations

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.privacy.models import DataDeletionRequest


@admin.register(DataDeletionRequest)
class DataDeletionRequestAdmin(ModelAdmin):
    """Append-only log de borrados solicitados por usuarios."""

    list_display = (
        "created_at",
        "status",
        "matched_photo_count",
        "deleted_photo_count",
        "deleted_embedding_count",
        "completed_at",
    )
    list_filter = ("status",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "matched_photo_count",
        "deleted_photo_count",
        "deleted_embedding_count",
        "status",
        "requester_ip_hash",
        "completed_at",
        "error_message",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
