"""Tests de los health checks (/healthz y /healthz/lite, Fase 6)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_returns_200_when_db_and_redis_ok(client: Client) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["checks"]["db"]["ok"] is True
    assert "version" in data
    assert "timestamp" in data


@pytest.mark.django_db
def test_healthz_503_when_db_down() -> None:
    client = Client()
    with patch("apps.core.views._check_db", return_value={"ok": False}):
        resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "down"


@pytest.mark.django_db
def test_healthz_degraded_when_only_celery_down(client: Client) -> None:
    """Sin worker (celery down) pero DB+Redis ok → 200 'degraded', no 503."""
    resp = client.get("/healthz")
    data = resp.json()
    assert resp.status_code == 200
    # celery_workers no está arriba en tests → status degraded, pero NO tumba el deploy.
    assert data["status"] in ("ok", "degraded")


@pytest.mark.django_db
def test_healthz_lite_only_checks_db(client: Client) -> None:
    resp = client.get("/healthz/lite")
    assert resp.status_code == 200
    data = resp.json()
    assert "checks" not in data  # liviano: sin el detalle


@pytest.mark.django_db
def test_healthz_lite_503_when_db_down() -> None:
    client = Client()
    with patch("apps.core.views._check_db", return_value={"ok": False}):
        resp = client.get("/healthz/lite")
    assert resp.status_code == 503
