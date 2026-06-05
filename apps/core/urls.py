"""URLs públicas básicas del core."""

from __future__ import annotations

from django.urls import path
from django.views.generic import TemplateView

from apps.events.views import HomeView

from . import views

app_name = "core"

urlpatterns = [
    path("", HomeView.as_view(), name="index"),
    path("healthz", views.healthz, name="healthz"),
    path("healthz/lite", views.healthz_lite, name="healthz_lite"),
    path("robots.txt", views.robots_txt, name="robots"),
    # PWA: manifest dinámico (usa site_name, no hardcodea el nombre)
    path(
        "manifest.webmanifest",
        TemplateView.as_view(
            template_name="manifest.webmanifest",
            content_type="application/manifest+json",
        ),
        name="manifest",
    ),
    # Páginas legales (Fase 6)
    path(
        "terminos/",
        TemplateView.as_view(template_name="public/terminos.html"),
        name="terminos",
    ),
    path(
        "cookies/",
        TemplateView.as_view(template_name="public/cookies.html"),
        name="cookies",
    ),
    path(
        "contacto/",
        TemplateView.as_view(template_name="public/contacto.html"),
        name="contacto",
    ),
]
