"""Tests de las páginas de error custom (Fase 6)."""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string
from django.test import Client, override_settings


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
def test_404_renders_custom_template() -> None:
    client = Client(raise_request_exception=False)
    resp = client.get("/esta-ruta-no-existe-xyz/")
    assert resp.status_code == 404
    assert "No encontramos esa página".encode() in resp.content
    assert b"RunFoto" in resp.content  # branding


def test_410_template_renders() -> None:
    html = render_to_string("errors/410.html")
    assert "ya no es válido" in html
    assert "RunFoto" in html


def test_429_template_renders() -> None:
    html = render_to_string("errors/429.html")
    assert "muy rápido" in html


def test_500_template_renders_self_contained() -> None:
    """El 500 NO depende de context processors ({{ site_name }} etc.)."""
    html = render_to_string("errors/500.html")
    assert "Algo salió mal" in html
    assert "RunFoto" in html  # wordmark hardcodeado, no {{ site_name }}
