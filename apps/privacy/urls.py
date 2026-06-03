"""URLs de privacidad."""

from __future__ import annotations

from django.urls import path

from apps.privacy.views import DeleteMyDataView, PrivacyPolicyView

app_name = "privacy"

urlpatterns = [
    path("", PrivacyPolicyView.as_view(), name="policy"),
    path("borrar-mis-datos/", DeleteMyDataView.as_view(), name="delete_my_data"),
]
