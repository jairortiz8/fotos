"""Tests del pipeline OCR — heurísticas + detección sintética."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.ml.ocr import (
    BibDetection,
    detect_bibs,
    is_bib_like,
    normalize_bib,
    reset_engines_for_tests,
)
from apps.ml.synthetic import write_synthetic_jpeg


# ---------------------------------------------------------------------------
# is_bib_like
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("1042", True),
        ("1", True),
        ("123456", True),
        ("A123", True),
        ("m42", True),  # case-insensitive después de upper
        (" 123 ", True),  # con espacios trimmeable
    ],
)
def test_is_bib_like_accepts(text: str, expected: bool) -> None:
    assert is_bib_like(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1234567",  # demasiado largo (7+)
        "ABC123",  # 2+ letras delante
        "123A",  # letra al final
        "12.3",  # caracteres especiales
        "1-2",
        "abc",  # solo letras
        " ",
    ],
)
def test_is_bib_like_rejects(text: str) -> None:
    assert is_bib_like(text) is False


def test_normalize_bib_uppercases_and_strips() -> None:
    assert normalize_bib(" a123 ") == "A123"
    assert normalize_bib("1042") == "1042"


# ---------------------------------------------------------------------------
# detect_bibs sobre imagen sintética
#
# Estos tests SÍ cargan PaddleOCR/EasyOCR de verdad (no mock) — son tests de
# integración. PaddleOCR puede tardar varios segundos la primera vez.
# Si se vuelven lentos para CI, marcarlos `@pytest.mark.slow` y excluirlos.
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_detect_bibs_finds_synthetic_number(tmp_path: Path) -> None:
    target = tmp_path / "synthetic.jpg"
    write_synthetic_jpeg("1042", target=target, width=1200, height=1600)

    reset_engines_for_tests()
    detections = detect_bibs(target)

    numbers = [d.number for d in detections]
    assert "1042" in numbers, f"Esperaba '1042'; recibí: {numbers}"
    # Cualquier detección debe tener engine válido
    for d in detections:
        assert d.engine in {"paddle", "easy"}
        assert 0 <= d.confidence <= 1
        # bbox válido (todos los valores en [0, 1])
        for v in d.bbox.values():
            assert 0 <= v <= 1


# ---------------------------------------------------------------------------
# Mocked engine paths (rápido, sin cargar PaddleOCR/EasyOCR real)
# ---------------------------------------------------------------------------
def _fake_paddle_response(text: str, conf: float) -> list:
    """Estructura que devuelve `PaddleOCR().ocr(...)`."""
    quad = [[100, 100], [200, 100], [200, 150], [100, 150]]
    return [[(quad, (text, conf))]]


def _fake_easy_response(text: str, conf: float) -> list:
    """Estructura que devuelve `easyocr.Reader().readtext(...)`."""
    quad = [[100, 100], [200, 100], [200, 150], [100, 150]]
    return [(quad, text, conf)]


def test_run_paddle_returns_only_bib_like(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """run_paddle_ocr descarta strings que no parecen dorsales."""
    from apps.ml import ocr

    img_path = write_synthetic_jpeg("9999", target=tmp_path / "x.jpg")

    class FakeEngine:
        def ocr(self, _path, cls=True):
            # Una respuesta que mezcla bib + ruido
            return [
                [
                    ([[0, 0], [50, 0], [50, 20], [0, 20]], ("1042", 0.95)),
                    ([[0, 30], [100, 30], [100, 50], [0, 50]], ("PUBLICIDAD", 0.92)),
                ]
            ]

    monkeypatch.setattr(ocr, "get_paddle_ocr", lambda: FakeEngine())
    detections = ocr.run_paddle_ocr(img_path)
    assert len(detections) == 1
    assert detections[0].number == "1042"
    assert detections[0].engine == "paddle"


def test_run_easy_returns_only_bib_like(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from apps.ml import ocr

    img_path = write_synthetic_jpeg("123", target=tmp_path / "y.jpg")

    class FakeReader:
        def readtext(self, _path):
            return [
                ([[0, 0], [50, 0], [50, 20], [0, 20]], "A123", 0.81),
                ([[0, 30], [50, 30], [50, 50], [0, 50]], "garbage!", 0.7),
            ]

    monkeypatch.setattr(ocr, "get_easy_ocr", lambda: FakeReader())
    detections = ocr.run_easy_ocr(img_path)
    assert len(detections) == 1
    assert detections[0].number == "A123"
    assert detections[0].engine == "easy"


def test_detect_bibs_falls_back_to_easy(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Si Paddle devuelve vacío, EasyOCR se invoca."""
    from apps.ml import ocr

    img_path = write_synthetic_jpeg("77", target=tmp_path / "z.jpg")

    monkeypatch.setattr(ocr, "run_paddle_ocr", lambda _p: [])
    easy_calls = {"n": 0}

    def fake_easy(_p):
        easy_calls["n"] += 1
        return [ocr.BibDetection(number="77", confidence=0.6, bbox={}, engine="easy")]

    monkeypatch.setattr(ocr, "run_easy_ocr", fake_easy)
    detections = ocr.detect_bibs(img_path)
    assert easy_calls["n"] == 1
    assert detections[0].number == "77"


def test_detect_bibs_runs_easy_when_paddle_finds_few(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Paddle con <2 candidatos: EasyOCR se corre igual y se suman (mejor recall)."""
    from apps.ml import ocr

    img_path = write_synthetic_jpeg("100", target=tmp_path / "few.jpg")
    # Paddle encuentra 1 (típico falso positivo de un cartel en foto real).
    monkeypatch.setattr(
        ocr,
        "run_paddle_ocr",
        lambda _p: [ocr.BibDetection(number="118", confidence=1.0, bbox={}, engine="paddle")],
    )
    easy_calls = {"n": 0}

    def fake_easy(_p):
        easy_calls["n"] += 1
        return [ocr.BibDetection(number="500", confidence=0.8, bbox={}, engine="easy")]

    monkeypatch.setattr(ocr, "run_easy_ocr", fake_easy)
    detections = ocr.detect_bibs(img_path)

    assert easy_calls["n"] == 1  # Easy corrió aunque Paddle encontró 1
    assert {d.number for d in detections} == {"118", "500"}  # se suman ambos engines


def test_detect_bibs_deduplicates_by_number(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Si paddle devuelve el mismo número 2 veces, queda solo el de mayor confidence."""
    from apps.ml import ocr

    img_path = write_synthetic_jpeg("1042", target=tmp_path / "dup.jpg")
    monkeypatch.setattr(
        ocr,
        "run_paddle_ocr",
        lambda _p: [
            ocr.BibDetection(number="1042", confidence=0.7, bbox={}, engine="paddle"),
            ocr.BibDetection(number="1042", confidence=0.95, bbox={}, engine="paddle"),
        ],
    )
    detections = ocr.detect_bibs(img_path)
    assert len(detections) == 1
    assert detections[0].confidence == 0.95


def test_engine_singletons_reset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`reset_engines_for_tests` limpia los singletons."""
    from apps.ml import ocr

    ocr._paddle = object()  # type: ignore[assignment]
    ocr._easy = object()  # type: ignore[assignment]
    ocr.reset_engines_for_tests()
    assert ocr._paddle is None
    assert ocr._easy is None


def test_detect_bibs_normal_skips_easy_when_paddle_enough(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """En modo normal, si Paddle ya trae ≥2 candidatos, NO corre EasyOCR."""
    from apps.ml import ocr

    img_path = write_synthetic_jpeg("100", target=tmp_path / "n.jpg")
    calls = {"easy": 0}
    monkeypatch.setattr(
        ocr,
        "run_paddle_ocr",
        lambda _p: [
            ocr.BibDetection(number="100", confidence=0.9, bbox={}, engine="paddle"),
            ocr.BibDetection(number="200", confidence=0.9, bbox={}, engine="paddle"),
        ],
    )

    def fake_easy(_p):  # type: ignore[no-untyped-def]
        calls["easy"] += 1
        return []

    monkeypatch.setattr(ocr, "run_easy_ocr", fake_easy)
    ocr.detect_bibs(img_path)  # exhaustive=False
    assert calls["easy"] == 0


def test_detect_bibs_exhaustive_runs_both_engines_and_upscaled_pass(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Exhaustivo: corre Paddle+Easy sobre el original Y la copia agrandada,
    aunque Paddle ya haya encontrado ≥2 (mejor recall de dorsales chicos)."""
    from contextlib import contextmanager

    from apps.ml import ocr

    img_path = write_synthetic_jpeg("100", target=tmp_path / "e.jpg")
    calls = {"paddle": 0, "easy": 0}

    def fake_paddle(_p):  # type: ignore[no-untyped-def]
        calls["paddle"] += 1
        return [
            ocr.BibDetection(number="100", confidence=0.9, bbox={}, engine="paddle"),
            ocr.BibDetection(number="200", confidence=0.9, bbox={}, engine="paddle"),
        ]

    def fake_easy(_p):  # type: ignore[no-untyped-def]
        calls["easy"] += 1
        return [ocr.BibDetection(number="300", confidence=0.8, bbox={}, engine="easy")]

    @contextmanager
    def fake_upscale(_p, **kw):  # type: ignore[no-untyped-def]
        yield tmp_path / "big.jpg"

    monkeypatch.setattr(ocr, "run_paddle_ocr", fake_paddle)
    monkeypatch.setattr(ocr, "run_easy_ocr", fake_easy)
    monkeypatch.setattr(ocr, "_upscaled_copy", fake_upscale)

    result = ocr.detect_bibs(img_path, exhaustive=True)
    assert {d.number for d in result} == {"100", "200", "300"}
    assert calls["paddle"] == 2  # original + agrandada
    assert calls["easy"] == 2  # corre SIEMPRE en exhaustivo + sobre la agrandada


# ---------------------------------------------------------------------------
# BibDetection dataclass
# ---------------------------------------------------------------------------
def test_bib_detection_is_frozen() -> None:
    """`@dataclass(frozen=True)` impide mutación tras crearlo."""
    from dataclasses import FrozenInstanceError

    det = BibDetection(number="1042", confidence=0.95, bbox={}, engine="paddle")
    with pytest.raises(FrozenInstanceError):
        det.number = "9999"  # type: ignore[misc]
