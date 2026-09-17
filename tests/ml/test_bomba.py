"""Bomba de descompresión: el freno de Pillow no se puede esquivar.

El límite de bytes del upload mide el archivo COMPRIMIDO, que es justo lo que
una bomba explota: un PNG de pocos MB que declara 30000x30000 pide gigabytes al
decodificarse. Pillow lo detecta; el problema era que el `except Exception` se
tragaba ese rechazo y reintentaba con `cv2.imdecode`, que no tiene ese freno.

Esto corre SÍNCRONO en el proceso web, que va con un solo worker: un request
bien armado tumbaba el sitio entero.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from apps.ml.face_recognition import MAX_PIXELES_DECODIFICADOS, InvalidImageError


def _png_que_miente(ancho: int, alto: int) -> bytes:
    """Un PNG chiquito cuyo header declara un tamaño enorme.

    No generamos la imagen de verdad (sería justamente la bomba): parcheamos el
    `size` que Pillow lee del header, que es lo que el guard mira.
    """
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_una_imagen_gigante_se_rechaza_y_no_cae_a_cv2(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from apps.ml import face_recognition as fr

    lados = int((MAX_PIXELES_DECODIFICADOS * 4) ** 0.5)  # 4x el tope
    original = Image.open

    def abrir_mintiendo(*a, **k):  # type: ignore[no-untyped-def]
        im = original(*a, **k)
        monkeypatch.setattr(type(im), "size", property(lambda _self: (lados, lados)))
        return im

    monkeypatch.setattr(Image, "open", abrir_mintiendo)

    # Si el guard no estuviera, esto caería a cv2.imdecode sin límite.
    with pytest.raises(InvalidImageError):
        fr.embedding_from_bytes(_png_que_miente(lados, lados))


def test_una_foto_normal_sigue_pasando_el_guard() -> None:
    """El tope tiene que dejar entrar cualquier cámara real (45-48 MP)."""
    from apps.ml.face_recognition import _rechazar_si_es_bomba

    class Falsa:
        size = (8192, 5464)  # Canon R5, 44.7 MP

    _rechazar_si_es_bomba(Falsa())  # no levanta
