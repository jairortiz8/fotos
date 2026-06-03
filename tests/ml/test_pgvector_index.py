"""Tests del índice HNSW de pgvector (ADR 0007)."""

from __future__ import annotations

import pytest
from django.db import connection


@pytest.mark.django_db
def test_hnsw_index_exists() -> None:
    """El índice HNSW sobre face_embeddings.embedding debe existir."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'photos_faceembedding'
              AND indexdef ILIKE '%hnsw%'
            """)
        rows = cur.fetchall()
    assert rows, "No se encontró un índice HNSW en photos_faceembedding"
    indexdef = rows[0][1].lower()
    assert "vector_cosine_ops" in indexdef


@pytest.mark.django_db
def test_cosine_distance_query_runs() -> None:
    """Sanity: una query con CosineDistance corre sin error."""
    from pgvector.django import CosineDistance

    from apps.photos.models import FaceEmbedding
    from tests.factories import PhotoFactory

    photo = PhotoFactory()
    FaceEmbedding.objects.create(photo=photo, embedding=[1.0] * 512)
    target = [1.0] * 512
    result = (
        FaceEmbedding.objects.annotate(dist=CosineDistance("embedding", target))
        .order_by("dist")
        .first()
    )
    assert result is not None
    assert result.dist == pytest.approx(0.0, abs=1e-5)
