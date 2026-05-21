"""Tests básicos del DataDeletionRequest."""

from __future__ import annotations

import hashlib

import pytest

from apps.privacy.models import DataDeletionRequest, DeletionStatus
from tests.factories import DataDeletionRequestFactory


@pytest.mark.django_db
def test_deletion_request_defaults() -> None:
    req = DataDeletionRequestFactory()
    assert req.status == DeletionStatus.PENDING
    assert req.matched_photo_count == 0
    assert req.deleted_photo_count == 0
    assert req.deleted_embedding_count == 0
    assert req.completed_at is None


@pytest.mark.django_db
def test_requester_ip_hash_format() -> None:
    """El hash de IP debe ser sha256 hex (64 chars)."""
    req = DataDeletionRequest.objects.create(
        requester_ip_hash=hashlib.sha256(b"1.2.3.4").hexdigest()
    )
    assert len(req.requester_ip_hash) == 64


@pytest.mark.django_db
def test_deletion_request_str() -> None:
    req = DataDeletionRequestFactory()
    assert "Borrado" in str(req)


@pytest.mark.django_db
def test_ordering_by_created_at_desc() -> None:
    older = DataDeletionRequestFactory()
    newer = DataDeletionRequestFactory()
    items = list(DataDeletionRequest.objects.all()[:2])
    assert items[0] == newer
    assert items[1] == older
