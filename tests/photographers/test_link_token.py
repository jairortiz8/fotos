"""Tests del PhotographerLink (token sha256, revocación, anonimización IP)."""

from __future__ import annotations

import datetime as dt
import hashlib

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.photographers.models import PhotographerLink
from tests.factories import (
    EventFactory,
    ExpiredPhotographerLinkFactory,
    PhotographerLinkFactory,
    RevokedPhotographerLinkFactory,
)


@pytest.mark.django_db
def test_generate_returns_plain_token_only_once() -> None:
    """El token plano se devuelve UNA vez en la creación; en DB solo el hash."""
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(
        event,
        name="Foto Test",
    )
    assert raw_token  # devuelto al admin
    assert link.token_hash != raw_token  # NO está en plano en DB
    assert link.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()


@pytest.mark.django_db
def test_token_is_hashed_never_plain() -> None:
    """Pegando contra DB raw, el token plano no aparece."""
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(event, name="X")
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT token_hash FROM photographers_photographerlink WHERE id = %s",
            [link.id],
        )
        stored = cur.fetchone()[0]
    assert stored != raw_token
    assert len(stored) == 64  # sha256 hex


@pytest.mark.django_db
def test_verify_token_correct() -> None:
    event = EventFactory()
    link, raw_token = PhotographerLink.generate_token_and_create(event, name="X")
    assert link.verify_token(raw_token) is True


@pytest.mark.django_db
def test_verify_token_incorrect() -> None:
    event = EventFactory()
    link, _ = PhotographerLink.generate_token_and_create(event, name="X")
    assert link.verify_token("wrong-token-xxx") is False
    assert link.verify_token("") is False


@pytest.mark.django_db
def test_is_valid_when_active_and_not_expired() -> None:
    link = PhotographerLinkFactory()
    assert link.is_valid() is True


@pytest.mark.django_db
def test_is_valid_returns_false_when_expired() -> None:
    link = ExpiredPhotographerLinkFactory()
    assert link.is_valid() is False


@pytest.mark.django_db
def test_is_valid_returns_false_when_revoked() -> None:
    link = RevokedPhotographerLinkFactory()
    assert link.is_valid() is False


@pytest.mark.django_db
def test_is_valid_returns_false_when_photo_limit_reached() -> None:
    link = PhotographerLinkFactory(photo_limit=10, photos_uploaded=10)
    assert link.is_valid() is False


@pytest.mark.django_db
def test_is_valid_true_when_below_photo_limit() -> None:
    link = PhotographerLinkFactory(photo_limit=10, photos_uploaded=5)
    assert link.is_valid() is True


@pytest.mark.django_db
def test_revoke_creates_audit_log() -> None:
    link = PhotographerLinkFactory()
    AuditLog.objects.all().delete()  # limpiar
    link.revoke(reason="test_reason")
    link.refresh_from_db()
    assert link.is_active is False
    assert link.revoked_at is not None
    assert link.revoked_reason == "test_reason"
    log = AuditLog.objects.get(action="photographer_link.revoked")
    assert log.target_type == "PhotographerLink"
    assert log.metadata.get("reason") == "test_reason"


@pytest.mark.django_db
def test_last_used_ip_is_anonymized() -> None:
    """Al guardar last_used_ip, el último octeto (IPv4) se zerifica."""
    link = PhotographerLinkFactory()
    link.last_used_ip = "10.20.30.45"
    link.last_used_at = timezone.now()
    link.save()
    link.refresh_from_db()
    assert link.last_used_ip == "10.20.30.0"


@pytest.mark.django_db
def test_expires_at_default_event_date_plus_30_days() -> None:
    event = EventFactory(date=timezone.now().date())
    link, _ = PhotographerLink.generate_token_and_create(event, name="X")
    expected = dt.datetime.combine(event.date, dt.time.max).replace(tzinfo=dt.UTC)
    expected += dt.timedelta(days=30)
    assert abs((link.expires_at - expected).total_seconds()) < 5
