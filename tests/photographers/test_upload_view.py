"""Tests del PhotographerUploadView."""

from __future__ import annotations

from unittest.mock import patch

import boto3
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.ml.synthetic import synthetic_jpeg_bytes
from apps.photographers.models import PhotographerLink
from apps.photos import storage as storage_module
from apps.photos.models import Photo, PhotoStatus
from tests.factories import EventFactory

BUCKET = "test-bucket"


@pytest.fixture
def r2_bucket(settings):  # type: ignore[no-untyped-def]
    """Bucket S3 mockeado con moto + R2 settings."""
    settings.R2_ENDPOINT_URL = ""  # moto-friendly
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET
    storage_module.reset_default_storage_for_tests()
    with mock_aws():
        boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        ).create_bucket(Bucket=BUCKET)
        yield
    storage_module.reset_default_storage_for_tests()


@pytest.fixture
def link_token() -> tuple[PhotographerLink, str]:
    event = EventFactory()
    return PhotographerLink.generate_token_and_create(event, name="Foto")


@pytest.fixture(autouse=True)
def no_celery_dispatch():
    """Evita que `process_photo.delay` dispare un task real durante tests."""
    with patch("apps.photos.tasks.process_photo.delay") as m:
        yield m


def _jpeg_upload(name: str = "shot.jpg", number: str = "1042") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name=name,
        content=synthetic_jpeg_bytes(number, width=600, height=900),
        content_type="image/jpeg",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_upload_valid_jpeg_creates_photo(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    link, raw_token = link_token
    url = reverse("photographer:upload", args=[raw_token])

    response = client.post(url, {"file": _jpeg_upload()})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == PhotoStatus.PROCESSING

    photo = Photo.objects.get(id=payload["id"])
    assert photo.event_id == link.event_id
    assert photo.photographer_link_id == link.id
    assert photo.original_key.startswith(f"events/{link.event.slug}/originals/")
    assert photo.original_key.endswith(".jpg")


@pytest.mark.django_db
def test_upload_dispatches_process_task(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    _link, raw_token = link_token
    client.post(reverse("photographer:upload", args=[raw_token]), {"file": _jpeg_upload()})
    assert no_celery_dispatch.called


@pytest.mark.django_db
def test_upload_increments_photos_uploaded(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    link, raw_token = link_token
    url = reverse("photographer:upload", args=[raw_token])
    # Contenido distinto en cada una (si no, la 2da sería duplicada y no contaría).
    client.post(url, {"file": _jpeg_upload("a.jpg", "1042")})
    client.post(url, {"file": _jpeg_upload("b.jpg", "2042")})
    link.refresh_from_db()
    assert link.photos_uploaded == 2


@pytest.mark.django_db
def test_upload_creates_audit_log(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    from apps.core.models import AuditLog

    AuditLog.objects.all().delete()
    _link, raw_token = link_token
    client.post(reverse("photographer:upload", args=[raw_token]), {"file": _jpeg_upload()})
    assert AuditLog.objects.filter(action="photo.uploaded").exists()


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_upload_rejects_non_jpeg(client: Client, link_token, r2_bucket) -> None:
    _link, raw_token = link_token
    fake = SimpleUploadedFile("not-a-photo.png", content=b"\x89PNG\r\n", content_type="image/png")
    response = client.post(reverse("photographer:upload", args=[raw_token]), {"file": fake})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_format"


@pytest.mark.django_db
def test_upload_rejects_oversize_file(client: Client, link_token, r2_bucket, settings) -> None:
    settings.PHOTO_UPLOAD_MAX_BYTES = 1024  # 1 KB para forzar el rechazo
    _link, raw_token = link_token
    response = client.post(
        reverse("photographer:upload", args=[raw_token]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "file_too_large"


@pytest.mark.django_db
def test_upload_rejects_when_photo_limit_reached(client: Client, link_token, r2_bucket) -> None:
    link, raw_token = link_token
    link.photo_limit = 5
    link.photos_uploaded = 5
    link.save()
    response = client.post(
        reverse("photographer:upload", args=[raw_token]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_upload_returns_410_for_invalid_token(client: Client, r2_bucket) -> None:
    response = client.post(
        reverse("photographer:upload", args=["definitely-not-valid"]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 410


@pytest.mark.django_db
def test_upload_returns_503_when_r2_not_configured(
    client: Client, link_token, settings, no_celery_dispatch
) -> None:
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = ""
    settings.R2_SECRET_ACCESS_KEY = ""
    settings.R2_BUCKET_NAME = ""
    storage_module.reset_default_storage_for_tests()

    _link, raw_token = link_token
    response = client.post(
        reverse("photographer:upload", args=[raw_token]),
        {"file": _jpeg_upload()},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "storage_not_configured"


@pytest.mark.django_db
def test_upload_no_file_returns_400(client: Client, link_token, r2_bucket) -> None:
    _link, raw_token = link_token
    response = client.post(reverse("photographer:upload", args=[raw_token]), {})
    assert response.status_code == 400
    assert response.json()["error"] == "no_file"


@pytest.mark.django_db
def test_upload_duplicate_content_returns_409(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    """Subir la MISMA foto dos veces al mismo evento → la 2da es 'duplicate' (409)."""
    link, raw_token = link_token
    url = reverse("photographer:upload", args=[raw_token])

    r1 = client.post(url, {"file": _jpeg_upload("a.jpg", "1042")})
    assert r1.status_code == 200

    r2 = client.post(url, {"file": _jpeg_upload("b.jpg", "1042")})  # mismo contenido
    assert r2.status_code == 409
    assert r2.json()["error"] == "duplicate"
    assert r2.json()["duplicate_of"] == r1.json()["id"]
    assert Photo.objects.filter(event=link.event).count() == 1


@pytest.mark.django_db
def test_upload_different_content_not_flagged_duplicate(
    client: Client, link_token, r2_bucket, no_celery_dispatch
) -> None:
    """Fotos distintas (otro contenido) NO se marcan como duplicadas."""
    link, raw_token = link_token
    url = reverse("photographer:upload", args=[raw_token])

    assert client.post(url, {"file": _jpeg_upload("a.jpg", "1042")}).status_code == 200
    assert client.post(url, {"file": _jpeg_upload("b.jpg", "7777")}).status_code == 200
    assert Photo.objects.filter(event=link.event).count() == 2


# ---------------------------------------------------------------------------
# Rate limit (600/m por token)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_upload_rate_limited_returns_429_not_403(client: Client, link_token, r2_bucket) -> None:
    """Pasado el límite, 429 + Retry-After: el portal lo trata como transitorio
    y reintenta. Antes era 403 (PermissionDenied) y el portal lo marcaba como
    error permanente (incidente UTCOM 2026-09-27: 2.258 fotos en "Error")."""
    _link, raw_token = link_token
    with patch("django_ratelimit.decorators.is_ratelimited", return_value=True):
        response = client.post(
            reverse("photographer:upload", args=[raw_token]), {"file": _jpeg_upload()}
        )
    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    assert response["Retry-After"] == "10"
    assert not Photo.objects.exists()


@pytest.mark.django_db
def test_upload_rate_limit_kicks_in_after_600_per_minute(
    client: Client, link_token, r2_bucket
) -> None:
    """El límite real: los primeros 600 pedidos pasan (acá sin archivo → 400),
    el 601 ya es 429."""
    _link, raw_token = link_token
    url = reverse("photographer:upload", args=[raw_token])
    # Reloj fijo: la ventana de django-ratelimit es de 60 s con un desfase según
    # el token; sin esto el loop podía cruzar el corte y el test fallaba al azar.
    with patch("django_ratelimit.core.time.time", return_value=1_790_000_000.0):
        statuses = [client.post(url, {}).status_code for _ in range(601)]
    assert set(statuses[:600]) == {400}
    assert statuses[600] == 429


# ---------------------------------------------------------------------------
# ¿Cuáles ya están subidas? (para no re-mandar al re-arrastrar la carpeta)
# ---------------------------------------------------------------------------
def _already(client: Client, token: str, files: object):  # type: ignore[no-untyped-def]
    import json

    return client.post(
        reverse("photographer:already_uploaded", args=[token]),
        data=json.dumps({"files": files}),
        content_type="application/json",
    )


@pytest.mark.django_db
def test_already_uploaded_matches_by_sanitized_name_and_size(client: Client, link_token) -> None:
    from tests.factories import PhotoFactory

    link, raw_token = link_token
    PhotoFactory(
        event=link.event,
        photographer_link=link,
        original_filename="IMG_2380.jpg",
        file_size=17_000_000,
    )
    PhotoFactory(
        event=link.event, photographer_link=link, original_filename="Foto_n_1.jpg", file_size=5
    )
    response = _already(
        client,
        raw_token,
        [
            ["IMG_2380.jpg", 17_000_000],  # misma foto → ya está
            ["IMG_2380.jpg", 16_999_999],  # mismo nombre, otro tamaño → no
            ["IMG_4186.jpg", 17_000_000],  # no subida
            ["Foto ñ 1.jpg", 5],  # el server compara con el nombre saneado
        ],
    )
    assert response.status_code == 200
    assert response.json() == {"uploaded": [True, False, False, True]}


@pytest.mark.django_db
def test_already_uploaded_ignores_other_links_and_deleted(client: Client, link_token) -> None:
    from tests.factories import PhotoFactory

    link, raw_token = link_token
    other, _ = PhotographerLink.generate_token_and_create(link.event, name="Otro")
    PhotoFactory(event=link.event, photographer_link=other, original_filename="A.jpg", file_size=10)
    PhotoFactory(
        event=link.event,
        photographer_link=link,
        original_filename="B.jpg",
        file_size=10,
        status=PhotoStatus.DELETED,
    )
    response = _already(client, raw_token, [["A.jpg", 10], ["B.jpg", 10]])
    assert response.json() == {"uploaded": [False, False]}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "files", [None, "x", [["solo-nombre"]], [["a.jpg", "no-numero"]], [["a.jpg", 1]] * 5001]
)
def test_already_uploaded_rejects_bad_payload(client: Client, link_token, files) -> None:  # type: ignore[no-untyped-def]
    _link, raw_token = link_token
    assert _already(client, raw_token, files).status_code == 400


@pytest.mark.django_db
def test_already_uploaded_requires_valid_token(client: Client) -> None:
    assert _already(client, "token-que-no-existe", [["a.jpg", 1]]).status_code == 410


@pytest.mark.django_db
def test_already_uploaded_rate_limited_returns_429(client: Client, link_token) -> None:
    _link, raw_token = link_token
    with patch("django_ratelimit.decorators.is_ratelimited", return_value=True):
        response = _already(client, raw_token, [["a.jpg", 1]])
    assert response.status_code == 429
