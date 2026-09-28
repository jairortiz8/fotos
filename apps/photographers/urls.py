"""URLs del portal de fotógrafo (`/u/<token>/`)."""

from __future__ import annotations

from django.urls import path

from apps.photographers.views import (
    PhotographerAlreadyUploadedView,
    PhotographerCoverView,
    PhotographerFeaturedUploadView,
    PhotographerPortalView,
    PhotographerSocialView,
    PhotographerUploadStatusView,
    PhotographerUploadView,
)

app_name = "photographer"

urlpatterns = [
    # Imagen destacada de la carpeta (pública, servida desde R2).
    path("cover/<int:link_id>.webp", PhotographerCoverView.as_view(), name="cover"),
    path("<str:token>/", PhotographerPortalView.as_view(), name="portal"),
    path("<str:token>/upload/", PhotographerUploadView.as_view(), name="upload"),
    path("<str:token>/status/", PhotographerUploadStatusView.as_view(), name="upload_status"),
    path(
        "<str:token>/ya-subidas/",
        PhotographerAlreadyUploadedView.as_view(),
        name="already_uploaded",
    ),
    path(
        "<str:token>/destacada/", PhotographerFeaturedUploadView.as_view(), name="featured_upload"
    ),
    path("<str:token>/redes/", PhotographerSocialView.as_view(), name="social"),
]
