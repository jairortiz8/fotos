"""Tests del pipeline de reconocimiento facial (mock InsightFace)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from apps.ml import face_recognition as fr


def _fake_face(emb: list[float], bbox: list[float], age: int, sex: str = "M") -> SimpleNamespace:
    return SimpleNamespace(
        embedding=np.array(emb, dtype=np.float32),
        bbox=np.array(bbox, dtype=np.float32),
        det_score=0.9,
        age=age,
        sex=sex,
    )


# ---------------------------------------------------------------------------
# normalize_embedding
# ---------------------------------------------------------------------------
def test_normalize_embedding_unit_length() -> None:
    out = fr.normalize_embedding(np.array([3.0, 4.0]))
    assert pytest.approx(np.linalg.norm(out), abs=1e-6) == 1.0


def test_normalize_embedding_zero_vector() -> None:
    out = fr.normalize_embedding(np.zeros(4))
    assert np.linalg.norm(out) == 0.0


# ---------------------------------------------------------------------------
# extract_faces (mock model)
# ---------------------------------------------------------------------------
def test_extract_faces_returns_embedding_512(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.synthetic import write_synthetic_jpeg

    img = write_synthetic_jpeg("1", target=tmp_path / "x.jpg")
    emb = [0.1] * 512
    monkeypatch.setattr(
        fr,
        "get_face_model",
        lambda: SimpleNamespace(get=lambda _img: [_fake_face(emb, [10, 10, 50, 50], 30)]),
    )
    dets = fr.extract_faces(img)
    assert len(dets) == 1
    assert dets[0].embedding.shape == (512,)
    assert dets[0].age == 30
    # embedding normalizado
    assert pytest.approx(np.linalg.norm(dets[0].embedding), abs=1e-5) == 1.0


def test_extract_faces_no_face(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.synthetic import write_synthetic_jpeg

    img = write_synthetic_jpeg("1", target=tmp_path / "x.jpg")
    monkeypatch.setattr(fr, "get_face_model", lambda: SimpleNamespace(get=lambda _img: []))
    assert fr.extract_faces(img) == []


def test_extract_faces_unreadable_image(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    assert fr.extract_faces(Path("/nope/does-not-exist.jpg")) == []


# ---------------------------------------------------------------------------
# embedding_from_bytes (selfie en memoria)
# ---------------------------------------------------------------------------
def test_embedding_from_bytes_single_face(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.synthetic import synthetic_jpeg_bytes

    monkeypatch.setattr(
        fr,
        "get_face_model",
        lambda: SimpleNamespace(get=lambda _img: [_fake_face([0.2] * 512, [0, 0, 40, 40], 25)]),
    )
    emb = fr.embedding_from_bytes(synthetic_jpeg_bytes("1"))
    assert emb.shape == (512,)
    assert pytest.approx(np.linalg.norm(emb), abs=1e-5) == 1.0


def test_embedding_from_bytes_no_face_raises(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.synthetic import synthetic_jpeg_bytes

    monkeypatch.setattr(fr, "get_face_model", lambda: SimpleNamespace(get=lambda _img: []))
    with pytest.raises(fr.NoFaceDetectedError):
        fr.embedding_from_bytes(synthetic_jpeg_bytes("1"))


def test_embedding_from_bytes_multiple_faces_raises(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.synthetic import synthetic_jpeg_bytes

    monkeypatch.setattr(
        fr,
        "get_face_model",
        lambda: SimpleNamespace(
            get=lambda _img: [
                _fake_face([0.1] * 512, [0, 0, 1, 1], 30),
                _fake_face([0.2] * 512, [2, 2, 3, 3], 40),
            ]
        ),
    )
    with pytest.raises(fr.MultipleFacesDetectedError):
        fr.embedding_from_bytes(synthetic_jpeg_bytes("1"))


def test_embedding_from_bytes_invalid_image() -> None:
    with pytest.raises(fr.InvalidImageError):
        fr.embedding_from_bytes(b"not-an-image")
