"""OCR pipeline para detección de dorsales.

Estrategia (ADR 0004):
    1. PaddleOCR (primario) — mejor accuracy en motion blur + ángulos.
    2. EasyOCR (fallback) — si Paddle devuelve cero candidatos.

Output: lista de `BibDetection` con (number, confidence, bbox, engine).
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
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


def detect_bibs(image_path: Path, *, exhaustive: bool = False) -> list[BibDetection]:
    """Orquesta Paddle + EasyOCR y devuelve candidatos únicos.

    Antes EasyOCR sólo corría si Paddle devolvía CERO. Problema real (visto en
    prod): en fotos con varios corredores, Paddle suele leer 1 número — a veces
    de un cartel o el fondo, no un dorsal — y ese único resultado "se tragaba" el
    fallback, perdiendo los dorsales reales. Ahora también corremos EasyOCR
    cuando Paddle encuentra POCOS (<2) candidatos, para mejorar el recall.

    Modo `exhaustive` (botón "Re-detectar" del dashboard): corre SIEMPRE los dos
    engines sobre el original Y sobre una copia agrandada 2x — los dorsales
    chicos/lejanos que a tamaño normal no cruzan el umbral de detección suelen
    leerse al agrandar. Es más lento (~2-3x) pero mejor recall. Trae más ruido →
    el admin cura (quita falsos positivos, agrega los que falten).

    OCR sigue siendo best-effort: el admin corrige/agrega dorsales en el
    dashboard (tab "Dorsales" / detalle de foto).
    """
    paddle = run_paddle_ocr(image_path)
    detections = list(paddle)
    if exhaustive or len(paddle) < 2:
        detections += run_easy_ocr(image_path)

    if exhaustive:
        # Pasada extra sobre una copia agrandada → recall de dorsales chicos en
        # fotos CHICAS (la copia sólo se genera si el original es < ~2600px).
        with _upscaled_copy(image_path) as big:
            if big is not None:
                detections += run_paddle_ocr(big)
                detections += run_easy_ocr(big)
        # Pasada extra por CUADRANTES en fotos GRANDES (cámara pro). Los engines
        # reescalan internamente la imagen a un lado fijo (~960px Paddle): en una
        # foto de 6000px un dorsal lejano les queda de ~20px e ilegible; en el
        # cuadrante queda ~2x más grande y se vuelve legible. Sólo Paddle por
        # tile (Easy es ~2x más lento y ya corrió sobre la imagen completa).
        with _detection_tiles(image_path) as tiles:
            for tile_path, geom in tiles:
                for det in run_paddle_ocr(tile_path):
                    detections.append(_remap_tile_detection(det, geom))

    # Dedup conservando la mayor confidence por número (independiente del engine).
    best_by_number: dict[str, BibDetection] = {}
    for det in detections:
        existing = best_by_number.get(det.number)
        if existing is None or det.confidence > existing.confidence:
            best_by_number[det.number] = det
    return list(best_by_number.values())


@contextmanager
def _upscaled_copy(image_path: Path, *, target_long_side: int = 2600) -> Iterator[Path | None]:
    """Crea (en un tempfile) una copia agrandada de la imagen para una pasada OCR
    extra; la borra al salir. Devuelve None si la imagen ya es grande (no agranda
    para no generar imágenes gigantes) o si algo falla (best-effort)."""
    tmp_path: Path | None = None
    try:
        try:
            from PIL import Image

            with Image.open(image_path) as img:
                rgb = img.convert("RGB")
                long_side = max(rgb.width, rgb.height)
                if long_side < target_long_side:
                    scale = min(2.5, target_long_side / long_side)
                    big = rgb.resize(
                        (int(rgb.width * scale), int(rgb.height * scale)),
                        Image.Resampling.LANCZOS,
                    )
                    fd, raw = tempfile.mkstemp(suffix=".jpg", prefix="rf_ocr_big_")
                    os.close(fd)
                    tmp_path = Path(raw)
                    big.save(tmp_path, "JPEG", quality=92)
        except Exception:
            logger.exception("Copia agrandada OCR falló: %s", image_path)
            tmp_path = None
        yield tmp_path
    finally:
        if tmp_path is not None:
            with suppress(OSError):
                tmp_path.unlink(missing_ok=True)


# Fotos con lado largo >= este umbral se parten en cuadrantes (las menores se
# agrandan con _upscaled_copy — mismo umbral para que no quede un hueco).
_TILE_MIN_LONG_SIDE = 2600
# Solape entre cuadrantes: un dorsal justo al medio cae COMPLETO en al menos
# un tile (un dorsal típico ocupa <10% del ancho de la foto; 15% lo cubre).
_TILE_OVERLAP = 0.15


@contextmanager
def _detection_tiles(image_path: Path) -> Iterator[list[tuple[Path, dict[str, float]]]]:
    """Parte una foto GRANDE en 4 cuadrantes con solape (tempfiles, se borran al
    salir) para una pasada OCR extra. Devuelve [] si la foto no llega al umbral
    o si algo falla (best-effort). Cada item es (path_del_tile, geometría en px
    para remapear los bboxes del tile a coordenadas de la imagen completa)."""
    tiles: list[tuple[Path, dict[str, float]]] = []
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            fw, fh = img.width, img.height
            if max(fw, fh) >= _TILE_MIN_LONG_SIDE:
                rgb = img.convert("RGB")
                tw = int(fw * (0.5 + _TILE_OVERLAP / 2))
                th = int(fh * (0.5 + _TILE_OVERLAP / 2))
                for ox in (0, fw - tw):
                    for oy in (0, fh - th):
                        crop = rgb.crop((ox, oy, ox + tw, oy + th))
                        fd, raw = tempfile.mkstemp(suffix=".jpg", prefix="rf_ocr_tile_")
                        os.close(fd)
                        path = Path(raw)
                        crop.save(path, "JPEG", quality=92)
                        geom = {"ox": ox, "oy": oy, "tw": tw, "th": th, "fw": fw, "fh": fh}
                        tiles.append((path, {k: float(v) for k, v in geom.items()}))
    except Exception:
        logger.exception("Tiles OCR fallaron: %s", image_path)
        for path, _geom in tiles:
            with suppress(OSError):
                path.unlink(missing_ok=True)
        tiles = []
    try:
        yield tiles
    finally:
        for path, _geom in tiles:
            with suppress(OSError):
                path.unlink(missing_ok=True)


def _remap_tile_detection(det: BibDetection, geom: dict[str, float]) -> BibDetection:
    """Convierte el bbox relativo-al-tile en relativo-a-la-imagen-completa."""
    b = det.bbox
    return BibDetection(
        number=det.number,
        confidence=det.confidence,
        engine=det.engine,
        bbox={
            "x": (geom["ox"] + b.get("x", 0.0) * geom["tw"]) / geom["fw"],
            "y": (geom["oy"] + b.get("y", 0.0) * geom["th"]) / geom["fh"],
            "w": b.get("w", 0.0) * geom["tw"] / geom["fw"],
            "h": b.get("h", 0.0) * geom["th"] / geom["fh"],
        },
    )


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
