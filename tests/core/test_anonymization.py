"""Tests de anonymize_ip y hash_ip (apps/core/utils.py, Fase 6)."""

from __future__ import annotations

from apps.core.utils import anonymize_ip, hash_ip


def test_anonymize_ipv4_zeros_last_octet() -> None:
    assert anonymize_ip("1.2.3.4") == "1.2.3.0"
    assert anonymize_ip("190.105.22.200") == "190.105.22.0"


def test_anonymize_ipv6_zeros_tail() -> None:
    # Conservamos los primeros 48 bits, el resto en cero.
    result = anonymize_ip("2001:db8:abcd:1234::1")
    assert result is not None
    assert result.startswith("2001:db8:abcd")
    assert result.endswith("::")


def test_anonymize_handles_invalid_and_empty() -> None:
    assert anonymize_ip(None) is None
    assert anonymize_ip("") is None
    assert anonymize_ip("no-soy-una-ip") is None


def test_hash_ip_is_sha256_hex() -> None:
    h = hash_ip("1.2.3.4")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_ip_consistent_within_same_salt() -> None:
    assert hash_ip("1.2.3.4", salt="2026-06-04") == hash_ip("1.2.3.4", salt="2026-06-04")


def test_hash_ip_differs_across_days() -> None:
    assert hash_ip("1.2.3.4", salt="2026-06-04") != hash_ip("1.2.3.4", salt="2026-06-05")


def test_hash_ip_differs_per_ip() -> None:
    salt = "2026-06-04"
    assert hash_ip("1.2.3.4", salt=salt) != hash_ip("1.2.3.5", salt=salt)


def test_hash_ip_default_salt_is_today() -> None:
    from django.utils import timezone

    today = timezone.now().strftime("%Y-%m-%d")
    assert hash_ip("1.2.3.4") == hash_ip("1.2.3.4", salt=today)
