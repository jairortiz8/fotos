"""URLs públicas básicas del core."""

from __future__ import annotations

from django.urls import path

from apps.events.views import HomeView

from . import views

app_name = "core"

urlpatterns = [
    path("", HomeView.as_view(), name="index"),
    path("healthz", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots"),
]
