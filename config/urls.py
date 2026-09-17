"""URL configuration de RunFoto."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

from apps.events.sitemaps import EventSitemap, StaticViewSitemap


def admin_login_con_limite(request: HttpRequest) -> HttpResponse:
    """El login del Django admin, con el freno de fuerza bruta puesto.

    Se monta ANTES de `admin.site.urls` para interceptar `/admin/django/login/`.
    Reusa el mismo chequeo que el dashboard (5 POST por IP cada 15 minutos) para
    que las dos puertas de la misma cuenta tengan la misma cerradura.
    """
    from apps.dashboard.views.auth import _login_rate_limited

    if request.method == "POST" and _login_rate_limited(request):
        return HttpResponse(
            _("Demasiados intentos. Probá de nuevo en 15 minutos."),
            status=429,
            content_type="text/plain; charset=utf-8",
        )
    return admin.site.login(request)


sitemaps = {
    "events": EventSitemap,
    "static": StaticViewSitemap,
}

urlpatterns = [
    # Dashboard admin custom (Fase 5) — herramienta principal de uso diario.
    path("dashboard/", include("apps.dashboard.urls", namespace="dashboard")),
    # Django admin (django-unfold) — fallback de emergencia, NO uso diario.
    # SEGURIDAD: su login va con el MISMO rate limit que el del dashboard. Es la
    # misma cuenta de super admin, así que dejarlo sin freno acá hacía inútil el
    # freno del otro: se probaban contraseñas contra esta puerta, sin límite.
    # CLAUDE.md §3 lo pide explícitamente y no se estaba cumpliendo en esta ruta.
    path("admin/django/login/", admin_login_con_limite, name="admin_login_limitado"),
    path("admin/django/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("u/", include("apps.photographers.urls", namespace="photographer")),
    # Rol invitado (community managers): ver galerías + descargar originales limpios.
    path("invitados/", include("apps.reviewers.urls", namespace="reviewer")),
    path("eventos/", include("apps.events.urls", namespace="events")),
    path("descargas/", include("apps.downloads.urls", namespace="downloads")),
    path("privacidad/", include("apps.privacy.urls", namespace="privacy")),
    path("", include("apps.core.urls", namespace="core")),
]

# Páginas de error custom (Fase 6). Django las usa con DEBUG=False.
handler404 = "apps.core.views.handler404"
handler500 = "apps.core.views.handler500"

# Debug toolbar solo en dev.
if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
        *urlpatterns,
    ]
