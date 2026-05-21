"""Admin de PhotographerLink."""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.photographers.models import PhotographerLink


@admin.register(PhotographerLink)
class PhotographerLinkAdmin(ModelAdmin):
    list_display = (
        "photographer_name",
        "event",
        "is_active_pill",
        "expires_at",
        "uploaded_vs_limit",
        "last_used_at",
        "created_at",
    )
    list_filter = ("is_active", "event__status")
    search_fields = ("photographer_name", "photographer_email", "event__name")
    readonly_fields = (
        "token_hash",
        "photos_uploaded",
        "last_used_at",
        "last_used_ip",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            _("Fotógrafo"),
            {
                "fields": (
                    "event",
                    "photographer_name",
                    "photographer_email",
                    "photographer_phone",
                )
            },
        ),
        (
            _("Vigencia"),
            {
                "fields": (
                    "is_active",
                    "expires_at",
                    "photo_limit",
                    "revoked_at",
                    "revoked_reason",
                )
            },
        ),
        (
            _("Token"),
            {
                "fields": ("token_hash",),
                "description": _(
                    "El token plano se ve UNA sola vez al generarlo. Acá guardamos sólo el SHA-256."
                ),
            },
        ),
        (
            _("Uso"),
            {
                "fields": ("photos_uploaded", "last_used_at", "last_used_ip"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Timestamps"),
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
    actions = ("revoke_links",)

    @admin.display(description=_("estado"), ordering="is_active")
    def is_active_pill(self, obj: PhotographerLink) -> str:
        if obj.is_valid():
            color, label = "#10B981", "activo"
        elif obj.revoked_at:
            color, label = "#EF4444", "revocado"
        else:
            color, label = "#F59E0B", "expirado"
        return format_html(
            '<span style="display:inline-flex;padding:4px 10px;border-radius:999px;'
            "background:{}1A;color:{};border:1px solid {}40;font-size:11px;"
            'text-transform:uppercase;letter-spacing:0.04em;">{}</span>',
            color,
            color,
            color,
            label,
        )

    @admin.display(description=_("subidas / límite"))
    def uploaded_vs_limit(self, obj: PhotographerLink) -> str:
        if obj.photo_limit is None:
            return f"{obj.photos_uploaded} / ∞"
        return f"{obj.photos_uploaded} / {obj.photo_limit}"

    @action(description=_("Revocar links seleccionados"))
    def revoke_links(self, request, queryset):
        count = 0
        for link in queryset:
            if link.is_active:
                link.revoke(reason="bulk_admin_revoke")
                count += 1
        self.message_user(
            request,
            f"{count} link(s) revocado(s).",
            messages.SUCCESS,
        )
