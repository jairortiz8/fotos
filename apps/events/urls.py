"""URLs públicas de eventos (galería + búsqueda)."""

from __future__ import annotations

from django.urls import path

from apps.events.views import EventCoverView, EventGalleryView
from apps.photos.views import FaceAvatarView, PhotoLightboxView
from apps.search.views import SelfieSearchView

app_name = "events"

urlpatterns = [
    path("<slug:slug>/", EventGalleryView.as_view(), name="gallery"),
    path("<slug:slug>/portada.webp", EventCoverView.as_view(), name="cover"),
    path("<slug:slug>/cara/<int:face_id>.webp", FaceAvatarView.as_view(), name="face_avatar"),
    path("<slug:slug>/buscar-selfie/", SelfieSearchView.as_view(), name="selfie_search"),
    path("<slug:slug>/foto/<int:photo_id>/", PhotoLightboxView.as_view(), name="lightbox"),
]
