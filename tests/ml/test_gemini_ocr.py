"""Tests del backend de OCR vía Gemini API (todo mockeado, sin red)."""

from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from apps.ml.gemini_ocr import GeminiOCRError, _to_detections, detect_bibs_gemini


@pytest.fixture
def race_jpg(tmp_path: Path) -> Path:
    target = tmp_path / "race.jpg"
    Image.new("RGB", (800, 600), "gray").save(target, "JPEG")
    return target


class _FakeResponse(io.BytesIO):
    """Respuesta mínima compatible con urlopen() como context manager."""

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _gemini_body(bibs: list[str]) -> bytes:
    return json.dumps(
        {"candidates": [{"content": {"parts": [{"text": json.dumps({"bibs": bibs})}]}}]}
    ).encode()


def test_detect_bibs_gemini_parses_and_filters(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    settings.GEMINI_API_KEY = "test-key"
    with patch(
        "apps.ml.gemini_ocr.urllib.request.urlopen",
        return_value=_FakeResponse(_gemini_body(["415", "a123", "no-bib!", "415"])),
    ):
        dets = detect_bibs_gemini(race_jpg)
    # "no-bib!" se filtra (no parece dorsal), "a123" se normaliza, "415" dedup.
    assert sorted(d.number for d in dets) == ["415", "A123"]
    assert all(d.engine == "gemini" for d in dets)


def test_detect_bibs_gemini_requires_key(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    settings.GEMINI_API_KEY = ""
    with pytest.raises(GeminiOCRError):
        detect_bibs_gemini(race_jpg)


def test_detect_bibs_gemini_wraps_network_errors(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    import urllib.error

    settings.GEMINI_API_KEY = "test-key"
    with (
        patch(
            "apps.ml.gemini_ocr.urllib.request.urlopen",
            side_effect=urllib.error.URLError("boom"),
        ),
        patch("apps.ml.gemini_ocr.time.sleep"),  # sin esperas reales en el retry
        pytest.raises(GeminiOCRError),
    ):
        detect_bibs_gemini(race_jpg)


def test_detect_bibs_gemini_no_candidates_gives_zero_without_retry(
    race_jpg: Path, settings
) -> None:  # type: ignore[no-untyped-def]
    """Respuesta sin candidates (p.ej. bloqueada): 0 dorsales y NO se reintenta
    (con temperature 0 volver a pedir da lo mismo y sólo gasta crédito)."""
    settings.GEMINI_API_KEY = "test-key"
    with patch(
        "apps.ml.gemini_ocr.urllib.request.urlopen",
        return_value=_FakeResponse(
            b'{"candidates": [], "promptFeedback": {"blockReason": "OTHER"}}'
        ),
    ) as call:
        assert detect_bibs_gemini(race_jpg) == []
    assert call.call_count == 1


def test_detect_bibs_gemini_ignores_trailing_data(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    """JSON válido + basura detrás ("Extra data") → se usa el primer objeto,
    en vez de caer al OCR local pesado."""
    settings.GEMINI_API_KEY = "test-key"
    text = '{"bibs": ["1203", "88"]}\n{"bibs": []}'
    body = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()
    with patch(
        "apps.ml.gemini_ocr.urllib.request.urlopen",
        return_value=_FakeResponse(body),
    ):
        dets = detect_bibs_gemini(race_jpg)
    assert sorted(d.number for d in dets) == ["1203", "88"]


def test_detect_bibs_gemini_non_list_bibs_gives_zero(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    settings.GEMINI_API_KEY = "test-key"
    text = '{"bibs": "1203"}'
    body = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()
    with patch(
        "apps.ml.gemini_ocr.urllib.request.urlopen",
        return_value=_FakeResponse(body),
    ) as call:
        assert detect_bibs_gemini(race_jpg) == []
    assert call.call_count == 1


def test_to_detections_handles_non_strings() -> None:
    """Números como int, None y vacíos no rompen; sólo queda lo bib-like."""
    dets = _to_detections([415, "168", None, ""])
    assert sorted(d.number for d in dets) == ["168", "415"]


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionResetError("reset"),
        http.client.RemoteDisconnected("closed"),
        http.client.IncompleteRead(b""),
    ],
)
def test_detect_bibs_gemini_retries_network_cuts(race_jpg: Path, settings, exc) -> None:  # type: ignore[no-untyped-def]
    """Los cortes al LEER la respuesta (que urllib no envuelve en URLError)
    usan los reintentos internos y terminan en GeminiOCRError."""
    settings.GEMINI_API_KEY = "test-key"
    with (
        patch("apps.ml.gemini_ocr.urllib.request.urlopen", side_effect=exc) as call,
        patch("apps.ml.gemini_ocr.time.sleep"),
        pytest.raises(GeminiOCRError),
    ):
        detect_bibs_gemini(race_jpg)
    assert call.call_count == 3


def test_detect_bibs_gemini_recovers_after_network_cut(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    settings.GEMINI_API_KEY = "test-key"
    with (
        patch(
            "apps.ml.gemini_ocr.urllib.request.urlopen",
            side_effect=[ConnectionResetError("reset"), _FakeResponse(_gemini_body(["77"]))],
        ),
        patch("apps.ml.gemini_ocr.time.sleep"),
    ):
        dets = detect_bibs_gemini(race_jpg)
    assert [d.number for d in dets] == ["77"]


def test_detect_bibs_gemini_timeout_is_not_retried_inline(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    """Un timeout ya retuvo el proceso `timeout` s (y Google puede seguir
    generando y cobrando): no se reintenta en el momento, lo hace Celery."""
    import urllib.error

    settings.GEMINI_API_KEY = "test-key"
    for exc in (TimeoutError("read timed out"), urllib.error.URLError(TimeoutError("timed out"))):
        with (
            patch("apps.ml.gemini_ocr.urllib.request.urlopen", side_effect=exc) as call,
            patch("apps.ml.gemini_ocr.time.sleep"),
            pytest.raises(GeminiOCRError),
        ):
            detect_bibs_gemini(race_jpg)
        assert call.call_count == 1


def test_detect_bibs_gemini_max_tokens_gives_zero_without_retry(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    """La foto que 'traba' al modelo (lista interminable de números): el tope
    la corta, da 0 dorsales y no se reintenta."""
    settings.GEMINI_API_KEY = "test-key"
    body = json.dumps(
        {
            "candidates": [
                {
                    "finishReason": "MAX_TOKENS",
                    "content": {"parts": [{"text": '{"bibs": ["1", "2", "3", "4'}]},
                }
            ]
        }
    ).encode()
    with patch(
        "apps.ml.gemini_ocr.urllib.request.urlopen", return_value=_FakeResponse(body)
    ) as call:
        assert detect_bibs_gemini(race_jpg) == []
    assert call.call_count == 1


def test_detect_bibs_gemini_payment_required_is_not_retried(race_jpg: Path, settings) -> None:  # type: ignore[no-untyped-def]
    import urllib.error

    settings.GEMINI_API_KEY = "test-key"
    err = urllib.error.HTTPError("u", 402, "Payment Required", {}, None)  # type: ignore[arg-type]
    with (
        patch("apps.ml.gemini_ocr.urllib.request.urlopen", side_effect=err) as call,
        patch("apps.ml.gemini_ocr.time.sleep"),
        patch("apps.ml.gemini_ocr.logger") as log,
        pytest.raises(GeminiOCRError),
    ):
        detect_bibs_gemini(race_jpg)
    assert call.call_count == 1
    assert "SIN CRÉDITO" in log.error.call_args[0][0]


def test_request_caps_output_tokens(race_jpg: Path) -> None:
    from apps.ml.gemini_ocr import _MAX_OUTPUT_TOKENS, _build_request_body

    config = json.loads(_build_request_body(race_jpg))["generationConfig"]
    assert config["maxOutputTokens"] == _MAX_OUTPUT_TOKENS <= 512
    assert config["temperature"] == 0


def test_request_rotates_vertical_photos_by_exif(tmp_path: Path) -> None:
    """Una foto vertical (píxeles acostados + EXIF Orientation=6) le llega a
    Gemini parada."""
    import base64

    from apps.ml.gemini_ocr import _build_request_body

    target = tmp_path / "vertical.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotar 90°
    Image.new("RGB", (800, 600), "gray").save(target, "JPEG", exif=exif)
    payload = json.loads(_build_request_body(target))
    data = payload["contents"][0]["parts"][0]["inline_data"]["data"]
    assert Image.open(io.BytesIO(base64.b64decode(data))).size == (600, 800)
