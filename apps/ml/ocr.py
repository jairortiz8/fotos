"""OCR pipeline para detección de dorsales.

Estrategia (ADR 0004):
    1. PaddleOCR (primario) — mejor accuracy en motion blur + ángulos.
    2. EasyOCR (fallback) — si Paddle devuelve cero candidatos.

Output: lista de `BibDetection` con (number, confidence, bbox, engine).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BibDetection:
    """Un dorsal candidato detectado por algún engine OCR."""

    number: str
    confidence: float
    bbox: dict[str, float]  # {"x", "y", "w", "h"} en porcentaje de la imagen [0..1]
    engine: str  # "paddle" | "easy"


# ---------------------------------------------------------------------------
# Heurísticas
# ---------------------------------------------------------------------------
def is_bib_like(text: str) -> bool:
    """¿El texto parece un número de dorsal?

    Aceptamos:
    - 1 a 6 caracteres
    - Solo dígitos (`1042`) o letra inicial + dígitos (`A123`, `M42`).
    """
    if not text:
        return False
    cleaned = text.strip().upper()
    length = len(cleaned)
    if not (1 <= length <= 6):
        return False
    if cleaned.isdigit():
        return True
    return bool(length >= 2 and cleaned[0].isalpha() and cleaned[1:].isdigit())


def normalize_bib(text: str) -> str:
    """Devuelve el texto en formato canónico (upper, sin espacios)."""
    return text.strip().upper()


# ---------------------------------------------------------------------------
# Singletons (carga lazy: PaddleOCR y EasyOCR pesan)
# ---------------------------------------------------------------------------
_paddle_lock = threading.Lock()
_easy_lock = threading.Lock()
_paddle: Any | None = None
_easy: Any | None = None


def get_paddle_ocr() -> Any:
    """Singleton de PaddleOCR. Carga del primer uso (~5-10s)."""
    global _paddle
    if _paddle is None:
        with _paddle_lock:
            if _paddle is None:
                from paddleocr import PaddleOCR

                _paddle = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    return _paddle


def get_easy_ocr() -> Any:
    global _easy
    if _easy is None:
        with _easy_lock:
            if _easy is None:
                import easyocr

                _easy = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _easy


# Helpers para tests / cleanup (no usar en runtime).
def reset_engines_for_tests() -> None:
    global _paddle, _easy
    _paddle = None
    _easy = None


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------
def run_paddle_ocr(image_path: Path) -> list[BibDetection]:
    """Corre PaddleOCR sobre la imagen y devuelve solo los candidatos bib-like."""
    try:
        ocr = get_paddle_ocr()
        raw = ocr.ocr(str(image_path), cls=True)
    except Exception:
        logger.exception("PaddleOCR falló en %s", image_path)
        return []

    detections: list[BibDetection] = []
    if not raw or raw == [None]:
        return detections

    # PaddleOCR devuelve `[[(bbox, (text, confidence)), ...]]`
    # bbox = [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] (4 esquinas)
    img_w, img_h = _image_size(image_path)
    for page in raw:
        if not page:
            continue
        for entry in page:
            try:
                quad, (text, conf) = entry
            except (TypeError, ValueError):
                continue
            if not is_bib_like(text):
                continue
            bbox = _quad_to_bbox(quad, img_w, img_h)
            detections.append(
                BibDetection(
                    number=normalize_bib(text),
                    confidence=float(conf),
                    bbox=bbox,
                    engine="paddle",
                )
            )
    return detections


def run_easy_ocr(image_path: Path) -> list[BibDetection]:
    """Fallback con EasyOCR."""
    try:
        reader = get_easy_ocr()
        raw = reader.readtext(str(image_path))
    except Exception:
        logger.exception("EasyOCR falló en %s", image_path)
        return []

    detections: list[BibDetection] = []
    img_w, img_h = _image_size(image_path)
    for entry in raw or []:
        try:
            quad, text, conf = entry
        except (TypeError, ValueError):
            continue
        if not is_bib_like(text):
            continue
        detections.append(
            BibDetection(
                number=normalize_bib(text),
                confidence=float(conf),
                bbox=_quad_to_bbox(quad, img_w, img_h),
                engine="easy",
            )
        )
    return detections


def detect_bibs(image_path: Path) -> list[BibDetection]:
    """Orquesta Paddle → EasyOCR (fallback) y devuelve candidatos únicos."""
    detections = run_paddle_ocr(image_path)
    if not detections:
        detections = run_easy_ocr(image_path)

    # Dedup conservando la mayor confidence por número (independiente del engine).
    best_by_number: dict[str, BibDetection] = {}
    for det in detections:
        existing = best_by_number.get(det.number)
        if existing is None or det.confidence > existing.confidence:
            best_by_number[det.number] = det
    return list(best_by_number.values())


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _image_size(image_path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(image_path) as img:
        return img.width, img.height


def _quad_to_bbox(quad: Any, img_w: int, img_h: int) -> dict[str, float]:
    """Convierte un quad de 4 esquinas a un bbox relativo (x, y, w, h) [0..1]."""
    try:
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        x0, y0 = min(xs), min(ys)
        x1, y1 = max(xs), max(ys)
    except (TypeError, IndexError, ValueError):
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}

    return {
        "x": max(0.0, x0 / img_w),
        "y": max(0.0, y0 / img_h),
        "w": max(0.0, min(1.0, (x1 - x0) / img_w)),
        "h": max(0.0, min(1.0, (y1 - y0) / img_h)),
    }
