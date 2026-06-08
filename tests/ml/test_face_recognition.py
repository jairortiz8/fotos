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


def _stateful_model(returns: list[list]) -> SimpleNamespace:  # type: ignore[type-arg]
    """Mock cuyo .get() devuelve returns[0], luego returns[1], ... por llamada.

    Sirve para simular el fallback: 1ra detección (imagen cruda) vacía, 2da
    (imagen escalada + con borde) con cara.
    """
    calls = {"n": 0}

    def get(_img):  # type: ignore[no-untyped-def]
        i = min(calls["n"], len(returns) - 1)
        calls["n"] += 1
        return returns[i]

    return SimpleNamespace(get=get)


def test_embedding_from_bytes_fallback_detects_tight_crop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Recorte ajustado: la 1ra detección no ve nada → el fallback (borde) sí."""
    from apps.ml.synthetic import synthetic_jpeg_bytes

    monkeypatch.setattr(
        fr,
        "get_face_model",
        lambda: _stateful_model([[], [_fake_face([0.3] * 512, [5, 5, 60, 60], 28)]]),
    )
    emb = fr.embedding_from_bytes(synthetic_jpeg_bytes("1"))
    assert emb.shape == (512,)
    assert pytest.approx(np.linalg.norm(emb), abs=1e-5) == 1.0


def test_embedding_from_bytes_fallback_picks_largest_face(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """En el fallback, varias detecciones (borde espurio) → elige la más grande,
    NO tira MultipleFacesDetectedError."""
    from apps.ml.synthetic import synthetic_jpeg_bytes

    big_emb = [1.0] + [0.0] * 511
    small_emb = [0.0, 1.0] + [0.0] * 510
    big = _fake_face(big_emb, [0, 0, 100, 100], 30)  # área 10000
    small = _fake_face(small_emb, [0, 0, 10, 10], 30)  # área 100
    monkeypatch.setattr(fr, "get_face_model", lambda: _stateful_model([[], [small, big]]))
    emb = fr.embedding_from_bytes(synthetic_jpeg_bytes("1"))
    expected = fr.normalize_embedding(np.array(big_emb, dtype=np.float32))
    assert np.allclose(emb, expected, atol=1e-5)


def test_embedding_from_bytes_no_face_even_after_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Imagen sin cara: ni la detección directa ni el fallback la ven → NoFace."""
    from apps.ml.synthetic import synthetic_jpeg_bytes

    monkeypatch.setattr(fr, "get_face_model", lambda: _stateful_model([[], []]))
    with pytest.raises(fr.NoFaceDetectedError):
        fr.embedding_from_bytes(synthetic_jpeg_bytes("1"))


def test_embedding_from_bytes_invalid_image() -> None:
    with pytest.raises(fr.InvalidImageError):
        fr.embedding_from_bytes(b"not-an-image")
