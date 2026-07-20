"""Tests de helpers de core/utils: bib format, OCR variants, hash."""

from __future__ import annotations

import pytest

from apps.core.utils import (
    bib_query_variants,
    generate_ocr_variants,
    hash_ip,
    is_valid_bib_format,
    normalize_bib_query,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1042", True),
        ("1", True),
        ("123456", True),
        ("A123", True),
        ("M42", True),
        (" 1042 ", True),  # se normaliza
        ("", False),
        ("1234567", False),  # 7 dígitos
        ("ABC123", False),  # 2+ letras
        ("12.3", False),
        ("1-2", False),
        ("abc", False),
    ],
)
def test_is_valid_bib_format(value: str, expected: bool) -> None:
    assert is_valid_bib_format(value) is expected


def test_normalize_bib_query() -> None:
    assert normalize_bib_query(" a123 ") == "A123"
    assert normalize_bib_query("1042") == "1042"


def test_bib_query_variants_ignores_leading_zeros() -> None:
    # "99" encuentra "099" (impreso con ceros) y viceversa.
    assert "099" in bib_query_variants("99")
    assert "99" in bib_query_variants("099")
    assert "015" in bib_query_variants("15")
    # No sobre-matchea números distintos.
    assert "99" not in bib_query_variants("990")
    # Alfanumérico: exacto, sin variantes.
    assert bib_query_variants("A15") == ["A15"]


def test_generate_ocr_variants_numeric() -> None:
    variants = generate_ocr_variants("8999")
    assert "9999" in variants  # 8 → 9
    assert "8999" not in variants  # no incluye el original


def test_generate_ocr_variants_non_numeric_empty() -> None:
    assert generate_ocr_variants("A123") == []


def test_generate_ocr_variants_respects_max() -> None:
    variants = generate_ocr_variants("8888", max_variants=3)
    assert len(variants) <= 3


def test_hash_ip_is_sha256() -> None:
    h = hash_ip("1.2.3.4")
    assert len(h) == 64
    assert hash_ip("1.2.3.4") == h  # determinístico
    assert hash_ip(None) == hash_ip("")  # None y "" coinciden
