"""Tests del modelo FaceEmbedding (pgvector + helpers)."""

from __future__ import annotations

import pytest

from apps.photos.models import FaceEmbedding
from tests.factories import (
    FaceEmbeddingFactory,
    MinorFaceEmbeddingFactory,
    PhotoFactory,
)


@pytest.mark.django_db
def test_face_embedding_vector_persists_round_trip() -> None:
    """Guardamos un vector de 512 dims y lo releemos sin pérdida."""
    photo = PhotoFactory()
    vec = [0.01 * i for i in range(512)]
    fe = FaceEmbedding.objects.create(photo=photo, embedding=vec, estimated_age=30)
    fe.refresh_from_db()
    # pgvector devuelve un numpy array; lo convertimos a list para comparar.
    stored = list(fe.embedding)
    assert len(stored) == 512
    assert abs(stored[0] - 0.0) < 1e-6
    assert abs(stored[100] - 1.0) < 1e-6  # 0.01 * 100


@pytest.mark.django_db
def test_minor_flag_blocks_public_visibility() -> None:
    """Si is_minor=True el preview público debería blurearse (Fase 4)."""
    fe = MinorFaceEmbeddingFactory()
    assert fe.is_minor is True
    assert fe.estimated_age == 14


@pytest.mark.django_db
def test_record_match_increments_count_and_timestamp() -> None:
    fe = FaceEmbeddingFactory()
    assert fe.last_matched_at is None
    fe.record_match()
    fe.refresh_from_db()
    assert fe.match_count == 1
    assert fe.last_matched_at is not None


@pytest.mark.django_db
def test_face_embedding_cosine_distance_query_works() -> None:
    """Sanity check: pgvector + operator coseno responde sin errores."""
    from pgvector.django import CosineDistance

    photo = PhotoFactory()
    target = [1.0] * 512
    FaceEmbedding.objects.create(photo=photo, embedding=target)
    FaceEmbedding.objects.create(photo=PhotoFactory(), embedding=[0.0] * 512)
    qs = FaceEmbedding.objects.annotate(dist=CosineDistance("embedding", target)).order_by("dist")
    closest = qs.first()
    assert closest is not None
    # El primero debería ser el embedding idéntico al target
    assert list(closest.embedding) == target
