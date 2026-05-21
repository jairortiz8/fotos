"""Admin de eventos."""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.events.models import Event, EventStatus


@admin.register(Event)
class EventAdmin(ModelAdmin):
    list_display = (
        "name",
        "date",
        "status_pill",
        "visibility",
        "photo_count",
        "pending_count",
        "photographer_count",
        "days_left",
    )
    list_filter = ("status", "visibility", "permanent_archive")
    search_fields = ("name", "slug", "location")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = (
        "photo_count",
        "pending_count",
        "photographer_count",
        "search_count",
        "download_count",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "date"

    fieldsets = (
        (
            _("Información"),
            {"fields": ("name", "slug", "date", "location", "description", "cover_image")},
        ),
        (_("Estado y visibilidad"), {"fields": ("status", "visibility")}),
        (
            _("Retención"),
            {
                "fields": (
                    "public_until",
                    "searchable_until",
                    "archive_until",
                    "permanent_archive",
                ),
                "description": _(
                    "Si dejás vacíos los `*_until`, se calculan en base a la fecha del evento "
                    "(90 / 180 / 365 días). Marcá `permanent_archive` para excluir el evento de "
                    "la política de borrado."
                ),
            },
        ),
        (
            _("Estadísticas"),
            {
                "fields": (
                    "photo_count",
                    "pending_count",
                    "photographer_count",
                    "search_count",
                    "download_count",
                ),
                "classes": ("collapse",),
            },
        ),
        (_("Timestamps"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = ("mark_archived", "mark_live")

    @admin.display(description=_("estado"), ordering="status")
    def status_pill(self, obj: Event) -> str:
        colors: dict[str, str] = {
            EventStatus.DRAFT.value: "#6B6B70",
            EventStatus.UPCOMING.value: "#00D4FF",
            EventStatus.LIVE.value: "#10B981",
            EventStatus.PUBLIC_CLOSED.value: "#F59E0B",
            EventStatus.SEARCHABLE_ONLY.value: "#F59E0B",
            EventStatus.ARCHIVED.value: "#6B6B70",
            EventStatus.PENDING_DELETION.value: "#EF4444",
            EventStatus.DELETED.value: "#EF4444",
        }
        c = colors.get(obj.status, "#A1A1A6")
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:6px;'
            "padding:4px 10px;border-radius:999px;background:{}1A;color:{};"
            "border:1px solid {}40;font-family:JetBrains Mono,monospace;"
            'font-size:11px;text-transform:uppercase;letter-spacing:0.04em;">{}</span>',
            c,
            c,
            c,
            obj.get_status_display(),
        )

    @admin.display(description=_("días para archivar"))
    def days_left(self, obj: Event) -> str:
        days = obj.days_until_archive()
        if days is None:
            return "—"
        return f"{days}d"

    @action(description=_("Marcar como archivado"))
    def mark_archived(self, request, queryset):
        updated = queryset.update(status=EventStatus.ARCHIVED)
        self.message_user(
            request,
            ngettext("%d evento archivado.", "%d eventos archivados.", updated) % updated,
            messages.SUCCESS,
        )

    @action(description=_("Marcar como en vivo"))
    def mark_live(self, request, queryset):
        updated = queryset.update(status=EventStatus.LIVE)
        self.message_user(
            request,
            ngettext("%d evento en vivo.", "%d eventos en vivo.", updated) % updated,
            messages.SUCCESS,
        )
