"""Tests para el stub de UserMFA — debe nacer inactivo y sin secret."""

from __future__ import annotations

import pytest

from apps.core.models import UserMFA
from tests.factories import SuperUserFactory, UserMFAFactory


@pytest.mark.django_db
def test_user_mfa_starts_inactive() -> None:
    """Cuando creamos un UserMFA con defaults, debe nacer inactivo."""
    mfa = UserMFAFactory()
    assert mfa.is_active is False
    assert mfa.activated_at is None
    assert mfa.backup_codes == []


@pytest.mark.django_db
def test_totp_secret_nullable_by_default() -> None:
    """El secret arranca NULL y la columna lo permite."""
    user = SuperUserFactory()
    mfa = UserMFA.objects.create(user=user)
    assert mfa.totp_secret is None
    # Re-leer desde DB
    mfa.refresh_from_db()
    assert mfa.totp_secret is None


@pytest.mark.django_db
def test_totp_secret_encrypts_at_rest() -> None:
    """Si guardamos un secret, en DB queda cifrado (cualquier valor != plain)."""
    user = SuperUserFactory()
    plain = "JBSWY3DPEHPK3PXP"
    mfa = UserMFA.objects.create(user=user, totp_secret=plain, is_active=True)
    # Vía ORM ya decifrado
    mfa.refresh_from_db()
    assert mfa.totp_secret == plain

    # Vía raw SQL debería estar distinto al plain
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT totp_secret FROM core_usermfa WHERE id = %s", [mfa.id])
        raw = cur.fetchone()[0]
    assert raw != plain
    assert len(raw) > len(plain)  # Fernet tokens son largos


@pytest.mark.django_db
def test_user_mfa_str_representation() -> None:
    mfa = UserMFAFactory()
    assert "inactivo" in str(mfa)
    mfa.is_active = True
    mfa.save()
    assert "activo" in str(mfa)
