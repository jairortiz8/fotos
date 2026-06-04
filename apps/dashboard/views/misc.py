"""Audit log, estadísticas y configuración."""

from __future__ import annotations

import csv
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import ListView, TemplateView

from apps.core.models import AuditLog
from apps.dashboard import services
from apps.dashboard.mixins import DashboardContextMixin


class AuditLogView(DashboardContextMixin, ListView):
    template_name = "dashboard/audit_log.html"
    context_object_name = "entries"
    active_nav = "audit"
    paginate_by = 50

    def get_queryset(self) -> Any:
        qs = AuditLog.objects.select_related("user")
        action = self.request.GET.get("action")
        if action:
            qs = qs.filter(action=action)
        target_type = self.request.GET.get("target_type")
        if target_type:
            qs = qs.filter(target_type=target_type)
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(action__icontains=q)
        rng = self.request.GET.get("range")
        if rng in ("7d", "30d"):
            days = 7 if rng == "7d" else 30
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["actions"] = list(
            AuditLog.objects.values_list("action", flat=True).distinct().order_by("action")
        )
        ctx["target_types"] = list(
            AuditLog.objects.exclude(target_type="")
            .values_list("target_type", flat=True)
            .distinct()
            .order_by("target_type")
        )
        ctx["filter_action"] = self.request.GET.get("action", "")
        ctx["filter_target"] = self.request.GET.get("target_type", "")
        ctx["filter_range"] = self.request.GET.get("range", "")
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class StatsView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/stats.html"
    active_nav = "stats"

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if request.GET.get("export") == "csv":
            return self._export_csv()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        daily = services.uploads_by_day(30)
        ctx["uploads_daily"] = daily
        ctx["uploads_daily_max"] = max((n for _, n in daily), default=1) or 1
        ctx["top_events"] = services.top_events_by_photos(10)
        ctx["status_distribution"] = services.status_distribution()
        return ctx

    def _export_csv(self) -> HttpResponse:
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="runfoto-stats.csv"'
        writer = csv.writer(resp)
        writer.writerow(["fecha", "fotos_subidas"])
        for day, n in services.uploads_by_day(30):
            writer.writerow([day.isoformat(), n])
        return resp


class SettingsView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/settings.html"
    active_nav = "settings"

    # Defaults de retención (hoy hardcodeados en Event.save(); se muestran readonly).
    RETENTION_DEFAULTS = {"public": 90, "searchable": 180, "archive": 365}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("password_form", PasswordChangeForm(self.request.user))
        ctx["retention_defaults"] = self.RETENTION_DEFAULTS
        from django.conf import settings as dj_settings

        ctx["site_name"] = dj_settings.SITE_NAME
        ctx["site_domain"] = dj_settings.SITE_DOMAIN
        return ctx

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # no desloguear tras cambiar pass
            AuditLog.log("admin.password_changed", user=self.staff_user)
            messages.success(request, _("Contraseña actualizada."))
            return redirect("dashboard:settings")
        ctx = self.get_context_data(password_form=form)
        return self.render_to_response(ctx)
