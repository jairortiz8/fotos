"""Tests del rol invitado (`/invitados/`): acceso + descarga del original LIMPIO."""

from __future__ import annotations

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.events.models import EventStatus, EventVisibility
from apps.ml.synthetic import synthetic_jpeg_bytes
from apps.photos import storage as storage_module
from apps.photos.models import PhotoStatus
from tests.factories import ApprovedPhotoFactory, EventFactory, SuperUserFactory, UserFactory

BUCKET = "test-bucket"


@pytest.fixture
def r2(settings):  # type: ignore[no-untyped-def]
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    storage_module.reset_default_storage_for_tests()
    cache.clear()
    with mock_aws():
        client = boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        )
        client.create_bucket(Bucket=BUCKET)
        yield client
    storage_module.reset_default_storage_for_tests()
    cache.clear()


def _body(resp) -> bytes:  # type: ignore[no-untyped-def]
    return b"".join(resp.streaming_content)


def _reviewer():  # type: ignore[no-untyped-def]
    return UserFactory(username="rev", is_staff=False, is_reviewer=True)


# --- Acceso -----------------------------------------------------------------
@pytest.mark.django_db
def test_index_redirects_anonymous() -> None:
    resp = Client().get(reverse("reviewer:index"))
    assert resp.status_code == 302
    assert "/invitados/entrar/" in resp.headers["Location"]


@pytest.mark.django_db
def test_index_redirects_normal_user() -> None:
    """Un usuario sin is_reviewer/is_staff NO entra (se lo manda al login)."""
    c = Client()
    c.force_login(UserFactory(username="normal", is_staff=False, is_reviewer=False))
    resp = c.get(reverse("reviewer:index"))
    assert resp.status_code == 302
    assert "/invitados/entrar/" in resp.headers["Location"]


@pytest.mark.django_db
def test_index_ok_for_reviewer() -> None:
    event = EventFactory(reviewer_visible=True)
    ApprovedPhotoFactory(event=event)
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:index"))
    assert resp.status_code == 200
    assert event.name.encode() in resp.content


@pytest.mark.django_db
def test_index_hides_non_visible_events() -> None:
    visible = EventFactory(name="Surf City Visible", reviewer_visible=True)
    hidden = EventFactory(name="Otro Evento Oculto", reviewer_visible=False)
    ApprovedPhotoFactory(event=visible)
    ApprovedPhotoFactory(event=hidden)
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:index"))
    assert visible.name.encode() in resp.content
    assert hidden.name.encode() not in resp.content


@pytest.mark.django_db
def test_index_ok_for_staff() -> None:
    c = Client()
    c.force_login(SuperUserFactory(username="admin2"))
    assert c.get(reverse("reviewer:index")).status_code == 200


@pytest.mark.django_db
def test_gallery_ok_for_reviewer() -> None:
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=True)
    ApprovedPhotoFactory(event=event)
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:gallery", kwargs={"slug": event.slug}))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_gallery_404_when_not_reviewer_visible() -> None:
    """Un evento NO expuesto a invitados no se abre ni con la URL directa."""
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=False)
    ApprovedPhotoFactory(event=event)
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:gallery", kwargs={"slug": event.slug}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_gallery_photographer_folders() -> None:
    """Carpetas por fotógrafo: vista de carpetas + filtrar por un fotógrafo."""
    from tests.factories import PhotographerLinkFactory

    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=True)
    link = PhotographerLinkFactory(event=event, photographer_name="Carlos Milan")
    ApprovedPhotoFactory(event=event, photographer_link=link)
    c = Client()
    c.force_login(_reviewer())

    folders = c.get(reverse("reviewer:gallery", kwargs={"slug": event.slug}) + "?vista=fotografos")
    assert folders.status_code == 200
    assert b"Carlos Milan" in folders.content

    filtered = c.get(
        reverse("reviewer:gallery", kwargs={"slug": event.slug}) + f"?fotografo={link.id}"
    )
    assert filtered.status_code == 200


@pytest.mark.django_db
def test_gallery_redirects_anonymous() -> None:
    event = EventFactory()
    resp = Client().get(reverse("reviewer:gallery", kwargs={"slug": event.slug}))
    assert resp.status_code == 302


# --- Búsqueda por dorsal / selfie -------------------------------------------
@pytest.mark.django_db
def test_reviewer_bib_search() -> None:
    from tests.factories import BibFactory

    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=True)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="1234")
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:gallery", kwargs={"slug": event.slug}) + "?bib=1234")
    assert resp.status_code == 200
    # La foto encontrada expone su link de descarga limpia.
    assert f"/invitados/foto/{photo.id}/descargar/".encode() in resp.content


@pytest.mark.django_db
def test_reviewer_selfie_page_ok() -> None:
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=True)
    c = Client()
    c.force_login(_reviewer())
    assert c.get(reverse("reviewer:selfie", kwargs={"slug": event.slug})).status_code == 200


@pytest.mark.django_db
def test_reviewer_selfie_404_when_not_visible() -> None:
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=False)
    c = Client()
    c.force_login(_reviewer())
    assert c.get(reverse("reviewer:selfie", kwargs={"slug": event.slug})).status_code == 404


@pytest.mark.django_db
def test_reviewer_selfie_post_without_file_returns_error(settings) -> None:  # type: ignore[no-untyped-def]
    settings.FACE_SEARCH_ENABLED = True
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=True)
    c = Client()
    c.force_login(_reviewer())
    resp = c.post(reverse("reviewer:selfie", kwargs={"slug": event.slug}))
    assert resp.status_code == 200  # vuelve al form con error, no procesa modelo


# --- Descarga del original LIMPIO (sin logos) -------------------------------
@pytest.mark.django_db
def test_download_serves_clean_original_even_when_branded(r2) -> None:  # type: ignore[no-untyped-def]
    """El invitado baja el ORIGINAL LIMPIO aunque el evento tenga logos —
    a diferencia de la descarga pública que sirve el branded."""
    event = EventFactory(
        status=EventStatus.LIVE,
        visibility=EventVisibility.PUBLIC,
        brand_overlay="surf_city",
        reviewer_visible=True,
    )
    okey = "events/e/originals/foto.jpg"
    bkey = "events/e/branded/foto.jpg"
    clean = synthetic_jpeg_bytes("111")
    branded = synthetic_jpeg_bytes("999")
    r2.put_object(Bucket=BUCKET, Key=okey, Body=clean)
    r2.put_object(Bucket=BUCKET, Key=bkey, Body=branded)
    photo = ApprovedPhotoFactory(
        event=event, original_key=okey, branded_key=bkey, original_filename="DSC_1.jpg"
    )

    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:download", kwargs={"photo_id": photo.id}))

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")
    assert "DSC_1.jpg" in resp["Content-Disposition"]
    assert _body(resp) == clean  # LIMPIO, no el branded


@pytest.mark.django_db
def test_download_redirects_anonymous(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, original_key="events/e/originals/x.jpg")
    resp = Client().get(reverse("reviewer:download", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 302
    assert "/invitados/entrar/" in resp.headers["Location"]


# --- Imagen limpia on-demand (sin logos) ------------------------------------
@pytest.mark.django_db
def test_clean_image_generates_and_redirects(r2) -> None:  # type: ignore[no-untyped-def]
    """La 1ª vez genera la versión limpia (sin logos) y la cachea en R2, luego
    redirige a su URL firmada — incluso en un evento con logos."""
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=True, brand_overlay="surf_city")
    key = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=key, Body=synthetic_jpeg_bytes("123"))
    photo = ApprovedPhotoFactory(event=event, original_key=key)
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:clean_image", kwargs={"photo_id": photo.id, "size": "thumb"}))
    assert resp.status_code == 302  # a la URL firmada de la versión limpia
    from apps.photos.storage import default_storage

    assert default_storage().exists(f"reviewer_clean/{event.slug}/{photo.id}_thumb.webp")


@pytest.mark.django_db
def test_clean_image_404_invalid_size(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=True)
    photo = ApprovedPhotoFactory(event=event, original_key="events/e/originals/x.jpg")
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:clean_image", kwargs={"photo_id": photo.id, "size": "gigante"}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_clean_image_404_when_not_reviewer_visible(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=False)
    photo = ApprovedPhotoFactory(event=event, original_key="events/e/originals/x.jpg")
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:clean_image", kwargs={"photo_id": photo.id, "size": "thumb"}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_404_when_event_not_reviewer_visible(r2) -> None:  # type: ignore[no-untyped-def]
    """No se baja el original de un evento que no está expuesto a invitados,
    aunque la foto esté aprobada (defensa contra adivinar el id)."""
    event = EventFactory(status=EventStatus.LIVE, reviewer_visible=False)
    key = "events/e/originals/x.jpg"
    r2.put_object(Bucket=BUCKET, Key=key, Body=synthetic_jpeg_bytes("1"))
    photo = ApprovedPhotoFactory(event=event, original_key=key)
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:download", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_download_404_for_non_approved(r2) -> None:  # type: ignore[no-untyped-def]
    from tests.factories import PhotoFactory

    photo = PhotoFactory(status=PhotoStatus.PENDING_REVIEW, original_key="events/e/originals/x.jpg")
    c = Client()
    c.force_login(_reviewer())
    resp = c.get(reverse("reviewer:download", kwargs={"photo_id": photo.id}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_login_rejects_non_reviewer() -> None:
    """El login del invitado rechaza a un usuario común (ni reviewer ni staff)."""
    UserFactory(username="pepe", is_staff=False, is_reviewer=False)
    resp = Client().post(
        reverse("reviewer:login"), {"username": "pepe", "password": "test-pass-1234"}
    )
    # Se queda en la página con error (no redirige a la galería).
    assert resp.status_code == 200
    assert b"no tiene acceso" in resp.content
