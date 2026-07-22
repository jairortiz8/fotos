"""URLs del rol invitado (`/invitados/`)."""

from __future__ import annotations

from django.urls import path

from apps.reviewers import views

app_name = "reviewer"

urlpatterns = [
    path("entrar/", views.ReviewerLoginView.as_view(), name="login"),
    path("salir/", views.ReviewerLogoutView.as_view(), name="logout"),
    path("", views.ReviewerIndexView.as_view(), name="index"),
    path(
        "foto/<int:photo_id>/descargar/", views.ReviewerPhotoDownloadView.as_view(), name="download"
    ),
    path("<slug:slug>/selfie/", views.ReviewerSelfieSearchView.as_view(), name="selfie"),
    path("<slug:slug>/", views.ReviewerGalleryView.as_view(), name="gallery"),
]
