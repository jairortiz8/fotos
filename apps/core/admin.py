"""Admin custom (Unfold) para los modelos de `core`."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.core.models import AuditLog, User, UserMFA


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    """Combinamos el UserAdmin de Django con el ModelAdmin de Unfold."""

    list_display = (
        "username",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "last_login",
        "created_at",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name")
    readonly_fields = ("last_login", "date_joined", "created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(UserMFA)
class UserMFAAdmin(ModelAdmin):
    list_display = ("user", "is_active", "activated_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at", "totp_secret", "backup_codes")
    fieldsets = (
        (
            _("Usuario"),
            {"fields": ("user",)},
        ),
        (
            _("Estado MFA"),
            {"fields": ("is_active", "activated_at")},
        ),
        (
            _("Secrets (sólo lectura)"),
            {
                "fields": ("totp_secret", "backup_codes"),
                "description": _(
                    "Estos campos quedan ocultos al admin; sólo el sistema los maneja."
                ),
            },
        ),
        (
            _("Timestamps"),
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    """Sólo lectura. El AuditLog es append-only."""

    list_display = ("created_at", "user", "action", "target_type", "target_id", "ip_address")
    list_filter = ("action", "target_type")
    search_fields = ("action", "target_id", "user__username", "user__email")
    readonly_fields = (
        "user",
        "action",
        "target_type",
        "target_id",
        "metadata",
        "ip_address",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
