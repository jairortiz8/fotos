"""Tests de autenticación y control de acceso del dashboard."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_dashboard_requires_login(client: Client) -> None:
    resp = client.get(reverse("dashboard:dashboard_home"))
    assert resp.status_code == 302
    assert "/dashboard/login/" in resp.headers["Location"]


@pytest.mark.django_db
def test_dashboard_requires_staff(client: Client, non_staff) -> None:  # type: ignore[no-untyped-def]
    client.force_login(non_staff)
    resp = client.get(reverse("dashboard:dashboard_home"))
    # Un user no-staff se trata como anónimo: redirige al login.
    assert resp.status_code == 302
    assert "/dashboard/login/" in resp.headers["Location"]


@pytest.mark.django_db
def test_event_list_requires_staff(client: Client, non_staff) -> None:  # type: ignore[no-untyped-def]
    client.force_login(non_staff)
    assert client.get(reverse("dashboard:event_list")).status_code == 302


@pytest.mark.django_db
def test_login_rate_limited_after_5_attempts(client: Client) -> None:
    url = reverse("dashboard:dashboard_login")
    last = None
    for _ in range(6):
        last = client.post(url, {"username": "x", "password": "bad"}, REMOTE_ADDR="9.9.9.9")
    assert last is not None
    assert b"Demasiados intentos" in last.content


@pytest.mark.django_db
def test_login_redirects_staff_to_dashboard(admin) -> None:  # type: ignore[no-untyped-def]
    admin.set_password("super-secret-123")
    admin.save()
    client = Client()
    resp = client.post(
        reverse("dashboard:dashboard_login"),
        {"username": admin.username, "password": "super-secret-123"},
        REMOTE_ADDR="9.9.9.10",
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == reverse("dashboard:dashboard_home")


@pytest.mark.django_db
def test_post_endpoints_csrf_protected(admin) -> None:  # type: ignore[no-untyped-def]
    """Las acciones POST NO son csrf_exempt (a diferencia del portal de fotógrafo)."""
    from tests.factories import PendingPhotoFactory

    photo = PendingPhotoFactory()
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin)
    resp = csrf_client.post(reverse("dashboard:approve_photo", kwargs={"pk": photo.id}))
    assert resp.status_code == 403
