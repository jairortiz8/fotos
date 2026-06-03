"""Sitemap de eventos públicos."""

from __future__ import annotations

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.events.models import Event, EventStatus, EventVisibility


class EventSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8
    protocol = "https"

    def items(self) -> list[Event]:
        return list(
            Event.objects.filter(
                visibility=EventVisibility.PUBLIC,
                status__in=[
                    EventStatus.UPCOMING,
                    EventStatus.LIVE,
                    EventStatus.PUBLIC_CLOSED,
                    EventStatus.SEARCHABLE_ONLY,
                ],
            ).order_by("-date")
        )

    def location(self, item: Event) -> str:
        return reverse("events:gallery", args=[item.slug])

    def lastmod(self, item: Event) -> object:
        return item.updated_at


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 1.0
    protocol = "https"

    def items(self) -> list[str]:
        return ["core:index"]

    def location(self, item: str) -> str:
        return reverse(item)
