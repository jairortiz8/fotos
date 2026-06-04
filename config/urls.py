"""URL configuration de RunFoto."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.events.sitemaps import EventSitemap, StaticViewSitemap

sitemaps = {
    "events": EventSitemap,
    "static": StaticViewSitemap,
}

urlpatterns = [
    # Dashboard admin custom (Fase 5) — herramienta principal de uso diario.
    path("dashboard/", include("apps.dashboard.urls", namespace="dashboard")),
    # Django admin (django-unfold) — fallback de emergencia, NO uso diario.
    path("admin/django/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("u/", include("apps.photographers.urls", namespace="photographer")),
    path("eventos/", include("apps.events.urls", namespace="events")),
    path("descargas/", include("apps.downloads.urls", namespace="downloads")),
    path("privacidad/", include("apps.privacy.urls", namespace="privacy")),
    path("", include("apps.core.urls", namespace="core")),
]

# Debug toolbar solo en dev.
if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
        *urlpatterns,
    ]
