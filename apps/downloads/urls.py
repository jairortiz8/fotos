"""URLs de descargas ZIP."""

from __future__ import annotations

from django.urls import path

from apps.downloads.views import (
    CreateZipDownloadView,
    PhotoDownloadView,
    ZipStatusView,
)

app_name = "downloads"

urlpatterns = [
    path("crear/", CreateZipDownloadView.as_view(), name="create"),
    path("estado/<int:download_id>/", ZipStatusView.as_view(), name="status"),
    path("foto/<int:photo_id>/", PhotoDownloadView.as_view(), name="photo"),
]
