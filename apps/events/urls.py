"""URLs públicas de eventos (galería + búsqueda)."""

from __future__ import annotations

from django.urls import path

from apps.events.views import EventGalleryView
from apps.photos.views import PhotoLightboxView

app_name = "events"

urlpatterns = [
    path("<slug:slug>/", EventGalleryView.as_view(), name="gallery"),
    path("<slug:slug>/foto/<int:photo_id>/", PhotoLightboxView.as_view(), name="lightbox"),
]
