"""Tests del lightbox de foto."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.events.models import EventStatus
from apps.photos.models import PhotoStatus
from tests.factories import ApprovedPhotoFactory, BibFactory, EventFactory, PhotoFactory


@pytest.mark.django_db
def test_lightbox_renders_approved_photo(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.status_code == 200
    assert response.context["photo"] == photo


@pytest.mark.django_db
def test_lightbox_includes_bib_badges(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="1042")
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert b"1042" in response.content


@pytest.mark.django_db
def test_lightbox_increments_view_count(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, view_count=0)
    client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    photo.refresh_from_db()
    assert photo.view_count == 1


@pytest.mark.django_db
def test_lightbox_404_when_photo_not_approved(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = PhotoFactory(event=event, status=PhotoStatus.PENDING_REVIEW)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_lightbox_404_when_event_archived(client: Client) -> None:
    event = EventFactory(status=EventStatus.ARCHIVED)
    photo = ApprovedPhotoFactory(event=event)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_lightbox_prev_next_navigation(client: Client) -> None:
    import datetime as dt

    from django.utils import timezone

    event = EventFactory(status=EventStatus.LIVE)
    p1 = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=2))
    p2 = ApprovedPhotoFactory(event=event, capture_time=timezone.now() - dt.timedelta(hours=1))
    p3 = ApprovedPhotoFactory(event=event, capture_time=timezone.now())
    response = client.get(reverse("events:lightbox", args=[event.slug, p2.id]))
    assert response.context["prev_photo"] == p1
    assert response.context["next_photo"] == p3


@pytest.mark.django_db
def test_lightbox_navigation_stays_within_bib_filter(client: Client) -> None:
    """Al entrar a una foto DESDE una búsqueda por dorsal, prev/next deben quedarse
    en las fotos de ESE dorsal — no saltar a la inmediata en el tiempo del evento
    completo. (Reportado por un usuario: 'me metía a un dorsal y el siguiente no
    seguía las del dorsal sino la inmediata en el tiempo'.)"""
    import datetime as dt

    from django.utils import timezone

    event = EventFactory(status=EventStatus.LIVE)
    now = timezone.now()
    # Fotos del dorsal 467 en T-30 y T-10.
    a = ApprovedPhotoFactory(event=event, capture_time=now - dt.timedelta(minutes=30))
    BibFactory(photo=a, number="467")
    b = ApprovedPhotoFactory(event=event, capture_time=now - dt.timedelta(minutes=10))
    BibFactory(photo=b, number="467")
    # Foto de OTRO dorsal EN EL MEDIO (T-20): es la "inmediata en el tiempo" pero
    # NO debe ser el next cuando venís filtrando por el 467.
    mid = ApprovedPhotoFactory(event=event, capture_time=now - dt.timedelta(minutes=20))
    BibFactory(photo=mid, number="999")

    # Con el filtro de dorsal 467: next = b (la otra del 467), saltándose `mid`.
    filtered = client.get(reverse("events:lightbox", args=[event.slug, a.id]), {"bib": "467"})
    assert filtered.context["prev_photo"] is None
    assert filtered.context["next_photo"] == b
    # Y las URLs de navegación preservan el ?bib para seguir filtrando.
    assert b"?bib=467" in filtered.content

    # Sin filtro: next = mid (la inmediata en el tiempo) — comportamiento por defecto.
    unfiltered = client.get(reverse("events:lightbox", args=[event.slug, a.id]))
    assert unfiltered.context["next_photo"] == mid


@pytest.mark.django_db
def test_lightbox_htmx_returns_partial(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    response = client.get(
        reverse("events:lightbox", args=[event.slug, photo.id]),
        HTTP_HX_REQUEST="true",
    )
    assert b"<html" not in response.content


@pytest.mark.django_db
def test_lightbox_photographer_name_falls_back_to_admin(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, photographer_link=None, uploaded_by_admin=True)
    response = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert response.context["photographer_name"] == "Admin"


@pytest.mark.django_db
def test_lightbox_shows_all_valid_bibs(client: Client) -> None:
    """Regresión: el visor mostraba solo UN dorsal (|first) — en fotos con
    varios corredores los demás 'no aparecían' aunque la búsqueda los hallara."""
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="415")
    BibFactory(photo=photo, number="222")
    BibFactory(photo=photo, number="999", rejected=True)  # rechazado: NO se muestra
    resp = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert resp.status_code == 200
    assert b"#415" in resp.content
    assert b"#222" in resp.content
    assert b"#999" not in resp.content


@pytest.mark.django_db
def test_gallery_card_shows_all_valid_bibs(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="77")
    BibFactory(photo=photo, number="88")
    BibFactory(photo=photo, number="666", rejected=True)
    resp = client.get(reverse("events:gallery", args=[event.slug]))
    assert b"#77" in resp.content
    assert b"#88" in resp.content
    assert b"#666" not in resp.content


@pytest.mark.django_db
def test_bib_chips_link_to_bib_search(client: Client) -> None:
    """Tocar un dorsal en la tarjeta o el visor lleva a la búsqueda de ese
    dorsal (todas las fotos de ese corredor)."""
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="415")

    gallery = client.get(reverse("events:gallery", args=[event.slug]))
    assert b'?bib=415"' in gallery.content  # chip de la tarjeta = link

    lightbox = client.get(reverse("events:lightbox", args=[event.slug, photo.id]))
    assert b'?bib=415"' in lightbox.content  # chip del visor = link
