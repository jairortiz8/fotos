"""Smoke tests de FAQ + contacto (IG) + términos (consentimiento)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_faq_page_renders(client: Client) -> None:
    resp = client.get(reverse("core:faq"))
    assert resp.status_code == 200
    assert b"Preguntas frecuentes" in resp.content


@pytest.mark.django_db
def test_contacto_shows_instagram(client: Client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.SITE_INSTAGRAM = "findyourfoto"
    resp = client.get(reverse("core:contacto"))
    assert resp.status_code == 200
    assert b"@findyourfoto" in resp.content
    assert b"Enviar mensaje" in resp.content


@pytest.mark.django_db
def test_terminos_has_participant_consent(client: Client) -> None:
    resp = client.get(reverse("core:terminos"))
    assert resp.status_code == 200
    assert b"Consentimiento del participante" in resp.content
