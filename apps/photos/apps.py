from __future__ import annotations

from django.apps import AppConfig


class PhotosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.photos"
    label = "photos"
    verbose_name = "Fotos"
