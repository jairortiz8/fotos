"""Tests del PhotographerLinkAdmin (pills + counter render)."""

from __future__ import annotations

import pytest

from apps.photographers.admin import PhotographerLinkAdmin
from apps.photographers.models import PhotographerLink
from tests.factories import (
    ExpiredPhotographerLinkFactory,
    PhotographerLinkFactory,
    RevokedPhotographerLinkFactory,
)


@pytest.fixture
def admin_instance() -> PhotographerLinkAdmin:
    from django.contrib import admin

    return PhotographerLinkAdmin(PhotographerLink, admin.site)


@pytest.mark.django_db
def test_is_active_pill_active(admin_instance: PhotographerLinkAdmin) -> None:
    link = PhotographerLinkFactory()
    html = admin_instance.is_active_pill(link)
    assert "activo" in html
    assert "#10B981" in html


@pytest.mark.django_db
def test_is_active_pill_revoked(admin_instance: PhotographerLinkAdmin) -> None:
    link = RevokedPhotographerLinkFactory()
    html = admin_instance.is_active_pill(link)
    assert "revocado" in html
    assert "#EF4444" in html


@pytest.mark.django_db
def test_is_active_pill_expired(admin_instance: PhotographerLinkAdmin) -> None:
    link = ExpiredPhotographerLinkFactory()
    html = admin_instance.is_active_pill(link)
    assert "expirado" in html
    assert "#F59E0B" in html


@pytest.mark.django_db
def test_uploaded_vs_limit_with_limit(admin_instance: PhotographerLinkAdmin) -> None:
    link = PhotographerLinkFactory(photo_limit=200, photos_uploaded=42)
    assert admin_instance.uploaded_vs_limit(link) == "42 / 200"


@pytest.mark.django_db
def test_uploaded_vs_limit_without_limit(admin_instance: PhotographerLinkAdmin) -> None:
    link = PhotographerLinkFactory(photo_limit=None, photos_uploaded=99)
    assert admin_instance.uploaded_vs_limit(link) == "99 / ∞"
