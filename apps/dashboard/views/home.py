"""Dashboard home — stat cards, eventos activos, pendientes, chart."""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.views.generic import TemplateView

from apps.dashboard import services
from apps.dashboard.mixins import DashboardContextMixin
from apps.events.models import Event, EventStatus


class DashboardHomeView(DashboardContextMixin, TemplateView):
    template_name = "dashboard/home.html"
    active_nav = "home"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["stats"] = services.dashboard_stats()
        ctx["active_events"] = list(
            Event.objects.filter(
                status__in=[
                    EventStatus.LIVE,
                    EventStatus.UPCOMING,
                    EventStatus.PUBLIC_CLOSED,
                    EventStatus.SEARCHABLE_ONLY,
                ]
            ).order_by("-date")[:5]
        )
        ctx["pending"] = services.pending_summary()
        hours = services.uploads_by_hour_today()
        ctx["uploads_by_hour"] = hours
        ctx["uploads_max"] = max(hours) if any(hours) else 1
        ctx["current_hour"] = timezone.localtime().hour
        return ctx
