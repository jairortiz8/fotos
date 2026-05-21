"""Tests del EncryptedCharField custom."""

from __future__ import annotations

import pytest

from apps.core.fields import _fernet


def test_fernet_roundtrip() -> None:
    fernet = _fernet()
    token = fernet.encrypt(b"hola")
    assert fernet.decrypt(token) == b"hola"
    # Tokens diferentes en runs sucesivos (incluye nonce)
    assert fernet.encrypt(b"hola") != token


@pytest.mark.django_db
def test_encrypted_field_round_trip_via_orm() -> None:
    """Guardar + releer un valor encriptado preserva el plaintext."""
    from apps.core.models import UserMFA
    from tests.factories import SuperUserFactory

    user = SuperUserFactory()
    secret = "ABC-XYZ-ROTATION-9"
    mfa = UserMFA.objects.create(user=user, totp_secret=secret)
    mfa.refresh_from_db()
    assert mfa.totp_secret == secret


@pytest.mark.django_db
def test_encrypted_field_null_passes_through() -> None:
    from apps.core.models import UserMFA
    from tests.factories import SuperUserFactory

    user = SuperUserFactory()
    mfa = UserMFA.objects.create(user=user, totp_secret=None)
    mfa.refresh_from_db()
    assert mfa.totp_secret is None
