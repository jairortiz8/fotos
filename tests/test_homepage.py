"""Tests de la landing pública temporal (Fase 0)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_homepage_returns_200(client: Client) -> None:
    response = client.get(reverse("core:index"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_homepage_contains_site_name(client: Client, site_name: str) -> None:
    """El nombre del site se inyecta vía context processor; nunca hardcodeado."""
    response = client.get(reverse("core:index"))
    assert site_name.encode() in response.content


@pytest.mark.django_db
def test_homepage_renders_wordmark(client: Client) -> None:
    """El partial `_partials/wordmark.html` agrega la clase del cuadradito."""
    response = client.get(reverse("core:index"))
    assert b"rf-wordmark" in response.content
    assert b"rf-wordmark__dot" in response.content


@pytest.mark.django_db
def test_homepage_uses_dark_theme_bg(client: Client) -> None:
    """La landing debe pintar el fondo dark (token --color-ink-0)."""
    response = client.get(reverse("core:index"))
    # El template usa `class="... bg-ink-0 ..."` en <body>.
    assert b"bg-ink-0" in response.content
