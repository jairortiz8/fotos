"""Tests de búsqueda por selfie (pgvector real + mock de extracción)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from apps.events.models import EventStatus
from apps.ml.face_recognition import NoFaceDetectedError
from apps.photos.models import FaceEmbedding
from tests.factories import ApprovedPhotoFactory, EventFactory


def _emb(*, dim0: float = 1.0) -> list[float]:
    """Embedding unitario apuntando al eje 0 (escalable con dim0)."""
    v = np.zeros(512, dtype=np.float32)
    v[0] = dim0
    v[1] = (1 - dim0**2) ** 0.5 if dim0 < 1 else 0.0
    n = np.linalg.norm(v)
    return (v / n).tolist() if n else v.tolist()


@pytest.fixture(autouse=True)
def locmem(settings):  # type: ignore[no-untyped-def]
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    yield
    cache.clear()


def _selfie() -> SimpleUploadedFile:
    return SimpleUploadedFile("me.jpg", b"\xff\xd8\xfffake", content_type="image/jpeg")


@pytest.mark.django_db
def test_selfie_search_returns_matches_above_threshold(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    match_photo = ApprovedPhotoFactory(event=event)
    FaceEmbedding.objects.create(photo=match_photo, embedding=_emb(dim0=1.0))  # similitud alta
    other = ApprovedPhotoFactory(event=event)
    FaceEmbedding.objects.create(photo=other, embedding=_emb(dim0=0.0))  # ortogonal

    target = np.array(_emb(dim0=1.0), dtype=np.float32)
    url = reverse("events:selfie_search", args=[event.slug])
    with patch("apps.ml.face_recognition.embedding_from_bytes", return_value=target):
        response = client.post(url, {"selfie": _selfie()})
    assert response.status_code == 200
    matches = response.context["matches"]
    assert match_photo in matches
    assert other not in matches


@pytest.mark.django_db
def test_selfie_search_orders_by_similarity(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    close = ApprovedPhotoFactory(event=event)
    FaceEmbedding.objects.create(photo=close, embedding=_emb(dim0=1.0))
    mid = ApprovedPhotoFactory(event=event)
    FaceEmbedding.objects.create(photo=mid, embedding=_emb(dim0=0.85))

    target = np.array(_emb(dim0=1.0), dtype=np.float32)
    with patch("apps.ml.face_recognition.embedding_from_bytes", return_value=target):
        response = client.post(
            reverse("events:selfie_search", args=[event.slug]), {"selfie": _selfie()}
        )
    matches = list(response.context["matches"])
    assert matches[0] == close
    assert matches[0].similarity >= matches[1].similarity


@pytest.mark.django_db
def test_selfie_search_does_not_persist_query_embedding(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    p = ApprovedPhotoFactory(event=event)
    FaceEmbedding.objects.create(photo=p, embedding=_emb(dim0=1.0))
    before = FaceEmbedding.objects.count()

    target = np.array(_emb(dim0=1.0), dtype=np.float32)
    with patch("apps.ml.face_recognition.embedding_from_bytes", return_value=target):
        client.post(reverse("events:selfie_search", args=[event.slug]), {"selfie": _selfie()})
    # No se creó ningún embedding nuevo (el del selfie nunca se persiste).
    assert FaceEmbedding.objects.count() == before


@pytest.mark.django_db
def test_selfie_search_updates_last_matched_at(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    p = ApprovedPhotoFactory(event=event)
    fe = FaceEmbedding.objects.create(photo=p, embedding=_emb(dim0=1.0))
    assert fe.last_matched_at is None

    target = np.array(_emb(dim0=1.0), dtype=np.float32)
    with patch("apps.ml.face_recognition.embedding_from_bytes", return_value=target):
        client.post(reverse("events:selfie_search", args=[event.slug]), {"selfie": _selfie()})
    fe.refresh_from_db()
    assert fe.last_matched_at is not None
    assert fe.match_count == 1


@pytest.mark.django_db
def test_selfie_search_no_face_handled(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    with patch("apps.ml.face_recognition.embedding_from_bytes", side_effect=NoFaceDetectedError):
        response = client.post(
            reverse("events:selfie_search", args=[event.slug]), {"selfie": _selfie()}
        )
    assert response.status_code == 200
    assert b"No detectamos una cara" in response.content


@pytest.mark.django_db
def test_selfie_search_no_selfie_returns_400(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    response = client.post(reverse("events:selfie_search", args=[event.slug]), {})
    assert response.status_code == 400


@pytest.mark.django_db
def test_selfie_search_404_in_archived_event(client: Client) -> None:
    event = EventFactory(status=EventStatus.ARCHIVED)
    response = client.get(reverse("events:selfie_search", args=[event.slug]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_selfie_search_rate_limited(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    ApprovedPhotoFactory(event=event)
    url = reverse("events:selfie_search", args=[event.slug])
    target = np.array(_emb(dim0=0.0), dtype=np.float32)
    last = 200
    with patch("apps.ml.face_recognition.embedding_from_bytes", return_value=target):
        for _ in range(22):
            r = client.post(url, {"selfie": _selfie()}, REMOTE_ADDR="3.3.3.3")
            last = r.status_code
            if last == 429:
                break
    assert last == 429


@pytest.mark.django_db
def test_selfie_search_get_renders_form(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    response = client.get(reverse("events:selfie_search", args=[event.slug]))
    assert response.status_code == 200
    assert b"no se guarda" in response.content  # banner de privacidad


# ---------------------------------------------------------------------------
# FACE_SEARCH_ENABLED=False (prod sin RAM para buffalo_l) — degradación amable
# ---------------------------------------------------------------------------
@pytest.mark.django_db
@override_settings(FACE_SEARCH_ENABLED=False)
def test_selfie_search_get_disabled_shows_notice(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    response = client.get(reverse("events:selfie_search", args=[event.slug]))
    assert response.status_code == 503
    assert b"no disponible" in response.content
    assert b"no se guarda" not in response.content  # NO es el form


@pytest.mark.django_db
@override_settings(FACE_SEARCH_ENABLED=False)
def test_selfie_search_post_disabled_never_loads_model(client: Client) -> None:
    """Lo crítico: con el flag apagado, el POST NO toca el modelo (evita el OOM)."""
    event = EventFactory(status=EventStatus.LIVE)
    url = reverse("events:selfie_search", args=[event.slug])
    with patch("apps.ml.face_recognition.embedding_from_bytes", new=MagicMock()) as m:
        response = client.post(url, {"selfie": _selfie()})
    assert response.status_code == 503
    m.assert_not_called()


@pytest.mark.django_db
@override_settings(FACE_SEARCH_ENABLED=False)
def test_gallery_hides_selfie_tab_when_disabled(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    ApprovedPhotoFactory(event=event)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert response.status_code == 200
    assert b"buscar-selfie" not in response.content  # tab oculto


@pytest.mark.django_db
def test_gallery_shows_selfie_tab_when_enabled(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    ApprovedPhotoFactory(event=event)
    response = client.get(reverse("events:gallery", args=[event.slug]))
    assert b"buscar-selfie" in response.content  # default: tab visible
