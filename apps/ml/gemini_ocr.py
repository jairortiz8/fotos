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
import http.client
import io
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

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
# Reintentos internos para transitorios (429/5xx/cortes de red). Un TIMEOUT no
# se reintenta acá (ver abajo): lo reintenta Celery más tarde.
_ATTEMPTS = 3
_RETRY_DELAY_S = 5
# Tope de la respuesta. Algunas fotos hacían que el modelo escribiera listas
# interminables de números (hasta ~5.000 "dorsales", decenas de miles de
# tokens): cada llamada tardaba >30 s, se reintentaba y, como Google cobra lo
# generado aunque cortemos por timeout, vaciaron el crédito prepago (UTCOM
# 2026-09-27 → HTTP 402). 12 dorsales son ~100 tokens: 256 sobra.
_MAX_OUTPUT_TOKENS = 256


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
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 402:
                logger.error("Gemini SIN CRÉDITO (HTTP 402): recargar en AI Studio → Billing")
            # 429/5xx son transitorios → reintentar; 4xx de config/pago no.
            if exc.code not in (429, 500, 502, 503, 504) or attempt == _ATTEMPTS:
                break
        except (OSError, http.client.HTTPException, ValueError) as exc:
            # Red: URLError y TimeoutError son OSError, pero urllib NO envuelve
            # los cortes al leer la respuesta (ConnectionResetError,
            # RemoteDisconnected, IncompleteRead, ssl.SSLError); ValueError = el
            # cuerpo llegó cortado. Un TIMEOUT no se reintenta acá: la llamada ya
            # retuvo el proceso `timeout` s (y Google puede seguir generando y
            # cobrando): lo reintenta Celery más tarde, con espera.
            last_error = exc
            if _is_timeout(exc) or attempt == _ATTEMPTS:
                break
        else:
            return _detections_from_body(body)
        time.sleep(_RETRY_DELAY_S * attempt)

    raise GeminiOCRError(f"{type(last_error).__name__}: {last_error}") from last_error


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)


def _detections_from_body(body: dict) -> list[BibDetection]:
    """Respuesta 200 → dorsales. Una respuesta INSERVIBLE (cortada por el tope,
    bloqueada, sin texto, JSON roto) da 0 dorsales SIN reintentar: con
    temperature 0 volver a pedir devuelve lo mismo y sólo gasta crédito. El
    admin puede corregir a mano o tocar "Re-detectar"."""
    candidates = body.get("candidates") or []
    if not candidates:
        block = (body.get("promptFeedback") or {}).get("blockReason")
        logger.warning("Gemini sin respuesta (blockReason=%s) → 0 dorsales", block)
        return []
    candidate = candidates[0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        logger.warning("Gemini cortado por el tope de %s tokens → 0 dorsales", _MAX_OUTPUT_TOKENS)
        return []
    try:
        text = candidate["content"]["parts"][0]["text"]
        return _to_detections(_parse_bibs(text))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Respuesta de Gemini inservible (%s) → 0 dorsales", exc)
        return []


def _build_request_body(image_path: Path) -> bytes:
    # exif_transpose: las fotos verticales le llegaban a Gemini acostadas
    # (la orientación viene en el EXIF, no en los píxeles).
    img = ImageOps.exif_transpose(Image.open(image_path))
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
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0,
                "maxOutputTokens": _MAX_OUTPUT_TOKENS,
            },
        }
    ).encode()


def _parse_bibs(text: str) -> list[object]:
    """Lee el PRIMER objeto JSON de la respuesta e ignora lo que venga después.

    A veces el modelo devuelve el JSON válido seguido de basura (un segundo
    objeto, texto suelto). `json.loads` lo rechazaba con "Extra data" → la foto
    caía al OCR local, y varias cayendo a la vez en el worker de 4 procesos
    agotaron sus hilos (incidente UTCOM 2026-09-27: ~900 fotos sin preview).
    """
    parsed, _end = json.JSONDecoder().raw_decode(text.strip())
    if not isinstance(parsed, dict):
        raise ValueError(f"respuesta no es objeto: {type(parsed).__name__}")
    bibs = parsed.get("bibs", [])
    if not isinstance(bibs, list):
        raise ValueError(f"'bibs' no es lista: {type(bibs).__name__}")
    return bibs


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
