from __future__ import annotations

from django.apps import AppConfig


class MlConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ml"
    label = "ml"
    verbose_name = "ML (OCR + caras)"
