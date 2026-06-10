"""OCR de dorsales vía Gemini API (visión).

Reemplaza a los engines locales (PaddleOCR + EasyOCR, ~4 GB de RAM residentes
en el worker) por una llamada HTTP (~1-2 s, centavos por foto). Validado contra
fotos reales del evento Camino a San Luis (2026-06-09): encuentra dorsales que
los engines locales no leían (incluidas fotos que requerían carga manual), y
falla en las mismas fotos borrosas en las que falla todo. El OCR local queda
como FALLBACK automático si la API no responde (ver tasks._detect_bibs).

Sin dependencias nuevas: usa urllib de la stdlib (regla §8 de CLAUDE.md).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from PIL import Image

from apps.ml.ocr import BibDetection, is_bib_like, normalize_bib

logger = logging.getLogger(__name__)

# Lado máximo de la imagen enviada (balance entre legibilidad de dorsales
# lejanos y costo/latencia del request).
_MAX_SIDE = 2048
_PROMPT = (
    "This is a race photo. List the bib numbers worn by runners that are clearly readable "
    "(printed bibs pinned on chest/waist). Do NOT include numbers from signs, clocks, "
    'banners or cars. Respond ONLY with JSON: {"bibs": ["123"]} — use [] if none readable.'
)
# Reintentos internos para transitorios (429/5xx/red). Si se agotan, el caller
# cae al OCR local — nunca se pierde el procesamiento de la foto.
_ATTEMPTS = 3
_RETRY_DELAY_S = 5


class GeminiOCRError(Exception):
    """La API de Gemini no pudo resolver el OCR (config, red, cuota, formato)."""


def detect_bibs_gemini(image_path: Path, *, timeout: int = 90) -> list[BibDetection]:
    """Detecta dorsales en una foto usando Gemini. Lanza GeminiOCRError si falla."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise GeminiOCRError("GEMINI_API_KEY no configurada")

    payload = _build_request_body(image_path)
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_OCR_MODEL}:generateContent"
    )

    last_error: Exception | None = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            request = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            numbers = json.loads(text).get("bibs", [])
            return _to_detections(numbers)
        except urllib.error.HTTPError as exc:
            last_error = exc
            # 429/5xx son transitorios → reintentar; 4xx de config no.
            if exc.code not in (429, 500, 502, 503, 504) or attempt == _ATTEMPTS:
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == _ATTEMPTS:
                break
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            # Respuesta con estructura inesperada — no tiene sentido reintentar.
            last_error = exc
            break
        time.sleep(_RETRY_DELAY_S * attempt)

    raise GeminiOCRError(f"{type(last_error).__name__}: {last_error}") from last_error


def _build_request_body(image_path: Path) -> bytes:
    img = Image.open(image_path)
    img.thumbnail((_MAX_SIDE, _MAX_SIDE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=88)
    return json.dumps(
        {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": base64.b64encode(buf.getvalue()).decode(),
                            }
                        },
                        {"text": _PROMPT},
                    ]
                }
            ],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0},
        }
    ).encode()


def _to_detections(numbers: list[object]) -> list[BibDetection]:
    """Normaliza + filtra lo que devuelve el modelo y dedup por número."""
    seen: dict[str, BibDetection] = {}
    for raw in numbers:
        number = normalize_bib(str(raw))
        if is_bib_like(number) and number not in seen:
            seen[number] = BibDetection(
                number=number,
                confidence=0.9,  # Gemini no da score por dorsal; valor fijo razonable
                bbox={},
                engine="gemini",
            )
    return list(seen.values())
