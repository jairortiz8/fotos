"""URLs del portal de fotógrafo (`/u/<token>/`)."""

from __future__ import annotations

from django.urls import path

from apps.photographers.views import (
    PhotographerPortalView,
    PhotographerUploadView,
)

app_name = "photographer"

urlpatterns = [
    path("<str:token>/", PhotographerPortalView.as_view(), name="portal"),
    path("<str:token>/upload/", PhotographerUploadView.as_view(), name="upload"),
]
