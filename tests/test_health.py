"""Tests del endpoint `/healthz` — verifica DB + Redis en runtime."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_healthz_returns_200_when_db_and_redis_are_up(client: Client) -> None:
    """Con la DB y Redis levantados, el endpoint devuelve 200 + JSON OK."""
    response = client.get(reverse("core:healthz"))
    assert response.status_code == 200

    data = response.json()
    assert data == {"status": "ok", "db": "ok", "redis": "ok"}


@pytest.mark.django_db
def test_healthz_content_type_is_json(client: Client) -> None:
    """El header Content-Type debe ser application/json."""
    response = client.get(reverse("core:healthz"))
    assert response["Content-Type"].startswith("application/json")
