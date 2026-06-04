"""Tests de la cola de aprobación, acciones individuales/bulk y dorsales."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import AuditLog
from apps.photos.models import Bib, BibSource, Photo, PhotoStatus
from tests.factories import (
    ApprovedPhotoFactory,
    BibFactory,
    EventFactory,
    PendingPhotoFactory,
)


@pytest.mark.django_db
def test_pending_lists_only_pending(admin_client: Client) -> None:
    event = EventFactory()
    pending = PendingPhotoFactory(event=event)
    ApprovedPhotoFactory(event=event)
    resp = admin_client.get(reverse("dashboard:pending_photos"))
    ids = {p.id for p in resp.context["photos"]}
    assert pending.id in ids
    assert resp.context["total_pending"] == 1


@pytest.mark.django_db
def test_pending_filters_by_event(admin_client: Client) -> None:
    e1, e2 = EventFactory(), EventFactory()
    p1 = PendingPhotoFactory(event=e1)
    PendingPhotoFactory(event=e2)
    resp = admin_client.get(reverse("dashboard:pending_photos") + f"?event={e1.slug}")
    ids = {p.id for p in resp.context["photos"]}
    assert ids == {p1.id}


@pytest.mark.django_db
def test_approve_changes_status_and_audits(admin_client: Client) -> None:
    photo = PendingPhotoFactory()
    resp = admin_client.post(reverse("dashboard:approve_photo", kwargs={"pk": photo.id}))
    assert resp.status_code == 200
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.APPROVED
    assert photo.approved_by_admin is True
    assert AuditLog.objects.filter(action="photo.approved", target_id=str(photo.id)).exists()


@pytest.mark.django_db
def test_approve_invalid_status_returns_400(admin_client: Client) -> None:
    photo = ApprovedPhotoFactory()
    resp = admin_client.post(reverse("dashboard:approve_photo", kwargs={"pk": photo.id}))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_reject_with_reason_saved(admin_client: Client) -> None:
    photo = PendingPhotoFactory()
    admin_client.post(
        reverse("dashboard:reject_photo", kwargs={"pk": photo.id}), {"reason": "Fuera de foco"}
    )
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.REJECTED
    assert photo.rejected_reason == "Fuera de foco"


@pytest.mark.django_db
def test_bulk_approve_updates_event_counters(admin_client: Client) -> None:
    event = EventFactory()
    photos = [PendingPhotoFactory(event=event) for _ in range(3)]
    resp = admin_client.post(
        reverse("dashboard:bulk_approve"), {"photo_ids[]": [p.id for p in photos]}
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 3
    event.refresh_from_db()
    assert event.pending_count == 0
    assert event.photo_count == 3
    assert AuditLog.objects.filter(action="photo.bulk_approved").exists()


@pytest.mark.django_db
def test_bulk_approve_rejects_more_than_100(admin_client: Client) -> None:
    resp = admin_client.post(
        reverse("dashboard:bulk_approve"), {"photo_ids[]": [str(i) for i in range(101)]}
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_reject(admin_client: Client) -> None:
    photos = [PendingPhotoFactory() for _ in range(2)]
    resp = admin_client.post(
        reverse("dashboard:bulk_reject"), {"photo_ids[]": [p.id for p in photos]}
    )
    assert resp.json()["updated"] == 2
    assert Photo.objects.filter(status=PhotoStatus.REJECTED).count() == 2


@pytest.mark.django_db
def test_add_manual_bib(admin_client: Client) -> None:
    photo = PendingPhotoFactory()
    resp = admin_client.post(
        reverse("dashboard:add_bib", kwargs={"pk": photo.id}), {"number": "a123"}
    )
    assert resp.status_code == 200
    bib = Bib.objects.get(photo=photo)
    assert bib.number == "A123"  # normalizado (upper)
    assert bib.source == BibSource.MANUAL_ADMIN
    assert AuditLog.objects.filter(action="bib.added").exists()


@pytest.mark.django_db
def test_remove_bib_marks_false_positive(admin_client: Client) -> None:
    photo = PendingPhotoFactory()
    bib = BibFactory(photo=photo)
    resp = admin_client.post(reverse("dashboard:remove_bib", kwargs={"pk": bib.id}))
    assert resp.status_code == 200
    bib.refresh_from_db()
    assert bib.rejected is True
    assert AuditLog.objects.filter(action="bib.rejected").exists()


@pytest.mark.django_db
def test_photo_detail_minor_warning(admin_client: Client) -> None:
    photo = PendingPhotoFactory(needs_minor_review=True)
    resp = admin_client.get(reverse("dashboard:photo_detail", kwargs={"pk": photo.id}))
    assert resp.status_code == 200
    assert resp.context["has_minor"] is True
