"""Tests del PhotoAdmin (pill + summary)."""

from __future__ import annotations

import pytest

from apps.photos.admin import PhotoAdmin
from apps.photos.models import Photo, PhotoStatus
from tests.factories import ApprovedPhotoFactory, BibFactory, PhotoFactory


@pytest.fixture
def admin_instance() -> PhotoAdmin:
    from django.contrib import admin

    return PhotoAdmin(Photo, admin.site)


@pytest.mark.django_db
def test_status_pill_renders(admin_instance: PhotoAdmin) -> None:
    photo = ApprovedPhotoFactory()
    html = admin_instance.status_pill(photo)
    assert "border-radius:999px" in html
    assert photo.get_status_display() in html


@pytest.mark.django_db
def test_bibs_summary_with_bibs(admin_instance: PhotoAdmin) -> None:
    photo = PhotoFactory()
    BibFactory(photo=photo, number="1001")
    BibFactory(photo=photo, number="1002")
    text = admin_instance.bibs_summary(photo)
    assert "1001" in text
    assert "1002" in text


@pytest.mark.django_db
def test_bibs_summary_empty(admin_instance: PhotoAdmin) -> None:
    photo = PhotoFactory()
    assert admin_instance.bibs_summary(photo) == "—"


@pytest.mark.django_db
def test_status_pill_for_each_status(admin_instance: PhotoAdmin) -> None:
    for status in [PhotoStatus.UPLOADING, PhotoStatus.APPROVED, PhotoStatus.REJECTED]:
        photo = PhotoFactory(status=status)
        html = admin_instance.status_pill(photo)
        assert "#" in html  # tiene color
