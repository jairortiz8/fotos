"""Tests del modelo Bib (unicidad, validación, confidence range)."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.photos.models import Bib, BibSource
from tests.factories import BibFactory, PhotoFactory


@pytest.mark.django_db
def test_unique_bib_per_photo_source() -> None:
    """No se puede insertar dos veces (photo, number, source)."""
    photo = PhotoFactory()
    Bib.objects.create(
        photo=photo,
        number="1234",
        source=BibSource.OCR_PADDLE,
        confidence=0.9,
    )
    with pytest.raises(IntegrityError):
        Bib.objects.create(
            photo=photo,
            number="1234",
            source=BibSource.OCR_PADDLE,
            confidence=0.85,
        )


@pytest.mark.django_db
def test_same_number_different_source_allowed() -> None:
    """Pero (photo, number) distinto source SÍ se permite — sirve para tracking del OCR."""
    photo = PhotoFactory()
    Bib.objects.create(
        photo=photo,
        number="1234",
        source=BibSource.OCR_PADDLE,
        confidence=0.9,
    )
    Bib.objects.create(
        photo=photo,
        number="1234",
        source=BibSource.OCR_EASY,
        confidence=0.7,
    )
    assert Bib.objects.filter(photo=photo, number="1234").count() == 2


@pytest.mark.django_db
def test_confidence_must_be_in_range() -> None:
    """confidence ∈ [0.0, 1.0] (CheckConstraint)."""
    photo = PhotoFactory()
    with pytest.raises(IntegrityError):
        Bib.objects.create(
            photo=photo,
            number="9999",
            source=BibSource.OCR_PADDLE,
            confidence=1.5,
        )


@pytest.mark.django_db
def test_validation_flags() -> None:
    bib = BibFactory()
    assert bib.is_validated is False
    assert bib.rejected is False
    bib.is_validated = True
    bib.save()
    bib.refresh_from_db()
    assert bib.is_validated is True


@pytest.mark.django_db
def test_bib_supports_alphanumeric_numbers() -> None:
    """Algunos dorsales son 'A123' o 'M-42' — el campo es CharField."""
    bib = BibFactory(number="A123")
    assert bib.number == "A123"


@pytest.mark.django_db
def test_bib_ordering_by_confidence_desc() -> None:
    photo = PhotoFactory()
    low = BibFactory(photo=photo, number="100", confidence=0.5)
    high = BibFactory(photo=photo, number="200", confidence=0.95)
    bibs = list(Bib.objects.filter(photo=photo))
    assert bibs[0] == high
    assert bibs[1] == low
