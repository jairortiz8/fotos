"""Tests de la cola de aprobación, acciones individuales/bulk y dorsales."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.photos.models import Bib, BibSource, Photo, PhotoStatus
from tests.factories import (
    ApprovedPhotoFactory,
    BibFactory,
    EventFactory,
    PendingPhotoFactory,
    PhotoFactory,
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
def test_approve_all_pending_by_photographer(admin_client: Client) -> None:
    """Aprueba TODAS las pendientes de un fotógrafo, sin tocar las de otro."""
    from apps.photographers.models import PhotographerLink

    event = EventFactory()
    link1, _t1 = PhotographerLink.generate_token_and_create(event, name="Foto 1")
    link2, _t2 = PhotographerLink.generate_token_and_create(event, name="Foto 2")
    mine = [PendingPhotoFactory(event=event, photographer_link=link1) for _ in range(3)]
    other = PendingPhotoFactory(event=event, photographer_link=link2)

    resp = admin_client.post(
        reverse("dashboard:approve_all_pending"),
        {"photographer": str(link1.id), "range": "all"},
    )
    assert resp.status_code == 302  # redirige de vuelta a la cola con el filtro

    for p in mine:
        p.refresh_from_db()
        assert p.status == PhotoStatus.APPROVED
    other.refresh_from_db()
    assert other.status == PhotoStatus.PENDING_REVIEW  # de otro fotógrafo: intacta
    assert AuditLog.objects.filter(action="photo.bulk_approved").exists()


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


# ---------------------------------------------------------------------------
# Detalle consciente del estado (aprobada / pendiente / rechazada)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_photo_detail_approved_shows_as_published(admin_client: Client) -> None:
    """Una foto aprobada se identifica como aprobada (no estampa "PENDIENTE")."""
    photo = ApprovedPhotoFactory()
    resp = admin_client.get(reverse("dashboard:photo_detail", kwargs={"pk": photo.id}))
    assert resp.status_code == 200
    assert resp.context["status_tone"] == "green"
    assert b"Publicada en la galer" in resp.content  # footer de aprobada
    assert b"PENDIENTE" not in resp.content  # ya no estampa el watermark de pendiente


@pytest.mark.django_db
def test_photo_detail_pending_shows_watermark(admin_client: Client) -> None:
    photo = PendingPhotoFactory()
    resp = admin_client.get(reverse("dashboard:photo_detail", kwargs={"pk": photo.id}))
    assert resp.context["status_tone"] == "amber"
    assert b"PENDIENTE" in resp.content


# ---------------------------------------------------------------------------
# Transiciones desde el detalle (no solo desde "pendiente")
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_approve_rejected_photo_restores(admin_client: Client) -> None:
    photo = PhotoFactory(status=PhotoStatus.REJECTED)
    resp = admin_client.post(reverse("dashboard:approve_photo", kwargs={"pk": photo.id}))
    assert resp.status_code == 200
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.APPROVED


@pytest.mark.django_db
def test_reject_approved_photo_unpublishes(admin_client: Client) -> None:
    photo = ApprovedPhotoFactory()
    resp = admin_client.post(reverse("dashboard:reject_photo", kwargs={"pk": photo.id}))
    assert resp.status_code == 200
    photo.refresh_from_db()
    assert photo.status == PhotoStatus.REJECTED


@pytest.mark.django_db
def test_approve_uploading_returns_400(admin_client: Client) -> None:
    """Aprobar una foto que todavía se está procesando no tiene sentido → 400."""
    photo = PhotoFactory(status=PhotoStatus.UPLOADING)
    resp = admin_client.post(reverse("dashboard:approve_photo", kwargs={"pk": photo.id}))
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Dorsales sobre fotos YA aprobadas (el caso de uso de Jair)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_add_bib_on_approved_photo(admin_client: Client) -> None:
    photo = ApprovedPhotoFactory()
    resp = admin_client.post(
        reverse("dashboard:add_bib", kwargs={"pk": photo.id}), {"number": "555"}
    )
    assert resp.status_code == 200
    assert Bib.objects.filter(photo=photo, number="555", rejected=False).exists()


@pytest.mark.django_db
def test_remove_bib_on_approved_photo(admin_client: Client) -> None:
    photo = ApprovedPhotoFactory()
    bib = BibFactory(photo=photo)
    resp = admin_client.post(reverse("dashboard:remove_bib", kwargs={"pk": bib.id}))
    assert resp.status_code == 200
    bib.refresh_from_db()
    assert bib.rejected is True


# ---------------------------------------------------------------------------
# Navegación entre fotos del evento + comportamiento de la cola
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_photo_detail_nav_between_event_photos(admin_client: Client) -> None:
    event = EventFactory()
    p1 = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=2))
    p2 = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=1))
    p3 = ApprovedPhotoFactory(event=event, capture_time=timezone.now())
    resp = admin_client.get(reverse("dashboard:photo_detail", kwargs={"pk": p2.id}))
    assert resp.status_code == 200
    assert resp.context["prev_id"] == p1.id
    assert resp.context["next_id"] == p3.id
    assert resp.context["nav_position"] == 2
    assert resp.context["nav_total"] == 3


@pytest.mark.django_db
def test_photo_detail_first_photo_has_no_prev(admin_client: Client) -> None:
    event = EventFactory()
    p1 = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=1))
    ApprovedPhotoFactory(event=event, capture_time=timezone.now())
    resp = admin_client.get(reverse("dashboard:photo_detail", kwargs={"pk": p1.id}))
    assert resp.context["prev_id"] is None
    assert resp.context["next_id"] is not None


@pytest.mark.django_db
def test_queue_mode_approve_advances_to_next_pending(admin_client: Client) -> None:
    event = EventFactory()
    p1 = PendingPhotoFactory(event=event)
    p2 = PendingPhotoFactory(event=event)
    Photo.objects.filter(pk=p1.pk).update(created_at=timezone.now() - dt.timedelta(minutes=5))
    Photo.objects.filter(pk=p2.pk).update(created_at=timezone.now())
    resp = admin_client.post(
        reverse("dashboard:approve_photo", kwargs={"pk": p1.id}),
        {"mode": "queue"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200  # renderiza el drawer de la siguiente pendiente
    assert str(p2.id) in resp.content.decode()
    p1.refresh_from_db()
    assert p1.status == PhotoStatus.APPROVED


@pytest.mark.django_db
def test_detail_mode_approve_triggers_page_refresh(admin_client: Client) -> None:
    """Sin mode=queue, una acción HTMX recarga la página (HX-Refresh) para que se
    vea el nuevo estado en la imagen + el drawer."""
    photo = PendingPhotoFactory()
    resp = admin_client.post(
        reverse("dashboard:approve_photo", kwargs={"pk": photo.id}), HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    assert resp["HX-Refresh"] == "true"


# ---------------------------------------------------------------------------
# OCR exhaustivo bajo demanda (botón "Re-detectar")
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_rerun_ocr_enqueues_exhaustive_and_sets_flag(admin_client: Client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from django.core.cache import cache

    photo = ApprovedPhotoFactory()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "apps.photos.tasks.run_ocr_on_photo.delay",
        lambda pid, exhaustive=False: captured.update(pid=pid, exhaustive=exhaustive),
    )
    resp = admin_client.post(reverse("dashboard:rerun_ocr", kwargs={"pk": photo.id}))
    assert resp.status_code == 200
    assert captured == {"pid": photo.id, "exhaustive": True}
    assert cache.get(f"ocr_rerun:{photo.id}") is not None  # flag "re-detectando"
    assert b"Re-detectando" in resp.content
    cache.delete(f"ocr_rerun:{photo.id}")


@pytest.mark.django_db
def test_bibs_section_get_shows_rerun_button(admin_client: Client) -> None:
    photo = ApprovedPhotoFactory()
    resp = admin_client.get(reverse("dashboard:bibs_section", kwargs={"pk": photo.id}))
    assert resp.status_code == 200
    assert b"Re-detectar" in resp.content
