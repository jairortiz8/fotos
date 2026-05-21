"""Tests del AuditLog (acciones admin + anonimización de IPs)."""

from __future__ import annotations

import pytest

from apps.core.models import AuditLog, anonymize_ip
from tests.factories import EventFactory, SuperUserFactory


@pytest.mark.django_db
def test_audit_log_records_admin_actions() -> None:
    user = SuperUserFactory()
    event = EventFactory()
    log = AuditLog.log(
        "event.created",
        target=event,
        user=user,
        metadata={"name": event.name},
        ip="192.168.1.123",
    )
    assert log.action == "event.created"
    assert log.target_type == "Event"
    assert log.target_id == str(event.pk)
    assert log.user == user
    assert log.metadata == {"name": event.name}


@pytest.mark.django_db
def test_audit_log_anonymizes_ipv4() -> None:
    log = AuditLog.log("test.action", ip="10.20.30.40")
    assert log.ip_address == "10.20.30.0"


@pytest.mark.django_db
def test_audit_log_anonymizes_ipv6() -> None:
    log = AuditLog.log("test.action", ip="2001:db8::abcd:1234")
    assert log.ip_address is not None
    assert log.ip_address != "2001:db8::abcd:1234"


def test_anonymize_ip_handles_none() -> None:
    assert anonymize_ip(None) is None
    assert anonymize_ip("") is None
    assert anonymize_ip("garbage") is None


def test_anonymize_ip_ipv4() -> None:
    assert anonymize_ip("192.168.1.123") == "192.168.1.0"


def test_anonymize_ip_ipv6() -> None:
    out = anonymize_ip("2001:db8:1234:5678::1")
    assert out is not None
    assert out.startswith("2001:db8:1234::")


@pytest.mark.django_db
def test_audit_log_string_representation() -> None:
    user = SuperUserFactory(username="admin42")
    log = AuditLog.log("event.created", user=user)
    text = str(log)
    assert "admin42" in text
    assert "event.created" in text


@pytest.mark.django_db
def test_audit_log_without_target() -> None:
    log = AuditLog.log("system.cron.ran")
    assert log.target_type == ""
    assert log.target_id == ""


@pytest.mark.django_db
def test_audit_log_save_anonymizes_direct_ip() -> None:
    """Si alguien crea instancia directa con IP cruda, save() anonimiza."""
    log = AuditLog(action="test", ip_address="172.16.10.50")
    log.save()
    log.refresh_from_db()
    assert log.ip_address == "172.16.10.0"
