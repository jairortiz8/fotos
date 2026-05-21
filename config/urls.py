"""URL configuration de RunFoto."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("u/", include("apps.photographers.urls", namespace="photographer")),
    path("", include("apps.core.urls", namespace="core")),
]

# Debug toolbar solo en dev.
if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
        *urlpatterns,
    ]
