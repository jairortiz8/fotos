"""Tests del overlay de logos de marca por evento (Surf City)."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from apps.photos import overlays


def _solid(w: int = 900, h: int = 600, color: tuple[int, int, int] = (0, 0, 0)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


# ---------------------------------------------------------------------------
# Assets + template registry
# ---------------------------------------------------------------------------
def test_assets_exist_and_load_rgba() -> None:
    for name in ("surf_city_left.png", "elsalvador_right.png"):
        assert (overlays.OVERLAY_DIR / name).exists(), f"falta el asset {name}"
    assert overlays._load_logo("surf_city_left.png").mode == "RGBA"
    assert overlays._load_logo("elsalvador_right.png").mode == "RGBA"


def test_is_valid_template() -> None:
    assert overlays.is_valid_template("surf_city")
    assert not overlays.is_valid_template("")
    assert not overlays.is_valid_template("bogus")


# ---------------------------------------------------------------------------
# apply_brand_overlay
# ---------------------------------------------------------------------------
def test_apply_brand_overlay_returns_rgb_same_size() -> None:
    out = overlays.apply_brand_overlay(_solid(1000, 700), "surf_city")
    assert out.mode == "RGB"
    assert out.size == (1000, 700)


def _has_bright(img: Image.Image, x0: int, x1: int, y0: int, y1: int) -> bool:
    for x in range(x0, x1, 6):
        for y in range(y0, y1, 6):
            r, g, b = img.getpixel((x, y))
            if r > 180 and g > 180 and b > 180:
                return True
    return False


def test_apply_brand_overlay_marks_both_bottom_corners() -> None:
    """Los 2 logos blancos aparecen en las esquinas de abajo; el centro-arriba
    (fondo negro) queda intacto."""
    out = overlays.apply_brand_overlay(_solid(1200, 800, (0, 0, 0)), "surf_city")
    w, h = out.size
    assert _has_bright(out, 0, w // 3, h * 3 // 4, h)  # abajo-izquierda
    assert _has_bright(out, w * 2 // 3, w, h * 3 // 4, h)  # abajo-derecha
    assert out.getpixel((w // 2, h // 4)) == (0, 0, 0)  # centro-arriba intacto


def test_apply_brand_overlay_works_portrait_and_landscape() -> None:
    """Aspecto-agnóstico: funciona en horizontal y vertical sin romperse."""
    for size in ((1600, 1000), (1000, 1600)):
        out = overlays.apply_brand_overlay(_solid(*size, (0, 0, 0)), "surf_city")
        assert out.size == size
        w, h = size
        assert _has_bright(out, 0, w // 3, h * 3 // 4, h)


def test_open_oriented_rotates_per_exif(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Una foto guardada horizontal + tag EXIF 'rotar 90°' (Orientation=6) se abre
    ya VERTICAL. Sin esto, las verticales de cámara salían acostadas."""
    from apps.photos.imaging import _open_oriented

    img = Image.new("RGB", (240, 120), (0, 0, 0))  # píxeles crudos: horizontal
    exif = img.getexif()
    exif[274] = 6  # 274 = Orientation; 6 = rotar para verse vertical
    p = tmp_path / "oriented.jpg"
    img.save(p, exif=exif)

    out = _open_oriented(p)
    assert out.size == (120, 240)  # ahora se ve vertical

    # Sin tag → no cambia nada.
    img2 = Image.new("RGB", (240, 120), (0, 0, 0))
    p2 = tmp_path / "plain.jpg"
    img2.save(p2)
    assert _open_oriented(p2).size == (240, 120)


def _bright_count(img: Image.Image) -> int:
    """Cuenta píxeles ~blancos (proxy del área que ocupan los logos)."""
    return sum(1 for r, g, b in img.getdata() if r > 180 and g > 180 and b > 180)


def test_landscape_logos_smaller_than_portrait_same_width() -> None:
    """En Surf City los logos van ~20% más chicos en HORIZONTAL; en vertical
    quedan como están. Con el mismo ANCHO, la horizontal debe tener claramente
    menos área de logo que la vertical."""
    land = overlays.apply_brand_overlay(_solid(1600, 1000, (0, 0, 0)), "surf_city")  # W>=H
    port = overlays.apply_brand_overlay(_solid(1600, 1700, (0, 0, 0)), "surf_city")  # W<H
    land_area = _bright_count(land)
    port_area = _bright_count(port)
    # 0.8 de escala lineal → ~0.64 de área. Chequeamos que sea sensiblemente menor.
    assert land_area < port_area * 0.8


def test_invalid_template_returns_unchanged() -> None:
    out = overlays.apply_brand_overlay(_solid(500, 500, (10, 20, 30)), "bogus")
    assert out.mode == "RGB"
    assert out.getpixel((250, 250)) == (10, 20, 30)
    assert out.getpixel((20, 480)) == (10, 20, 30)  # sin logos en la esquina


# ---------------------------------------------------------------------------
# Gating en el pipeline (_try_brand_overlay)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_try_brand_overlay_gated_by_event_flag() -> None:
    from apps.photos.imaging import _try_brand_overlay
    from tests.factories import EventFactory, PhotoFactory

    base = _solid(800, 600)

    photo_on = PhotoFactory(event=EventFactory(brand_overlay="surf_city"))
    out = _try_brand_overlay(base, photo_on)
    assert out is not None
    assert out.size == (800, 600)

    photo_off = PhotoFactory(event=EventFactory(brand_overlay=""))
    assert _try_brand_overlay(base, photo_off) is None


@pytest.mark.django_db
def test_try_brand_overlay_invalid_template_falls_back() -> None:
    """Un template inexistente NO aplica overlay (cae al watermark)."""
    from apps.photos.imaging import _try_brand_overlay
    from tests.factories import EventFactory, PhotoFactory

    photo = PhotoFactory(event=EventFactory(brand_overlay="no_existe"))
    assert _try_brand_overlay(_solid(400, 400), photo) is None


# ---------------------------------------------------------------------------
# Original con logos para DESCARGA (generate_branded_original + download_key)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_generate_branded_original_none_without_overlay() -> None:
    """Evento normal → no genera versión con logos (ni abre la imagen)."""
    from apps.photos.imaging import generate_branded_original
    from tests.factories import EventFactory, PhotoFactory

    photo = PhotoFactory(event=EventFactory(brand_overlay=""))
    assert generate_branded_original(photo, img_object=_solid(400, 400)) is None


@pytest.mark.django_db
def test_generate_branded_original_creates_jpeg_with_logos() -> None:
    """Evento Surf City → sube a R2 un JPEG full-res con los logos en las
    esquinas de abajo, y devuelve su key (.jpg)."""
    import boto3
    from django.test import override_settings
    from moto import mock_aws

    from apps.photos import storage as storage_module
    from apps.photos.imaging import generate_branded_original
    from tests.factories import EventFactory, PhotoFactory

    with override_settings(
        R2_ENDPOINT_URL="",
        R2_ACCESS_KEY_ID="AKIA-TEST",
        R2_SECRET_ACCESS_KEY="SECRET-TEST",
        R2_BUCKET_NAME="test-bucket",
    ):
        storage_module.reset_default_storage_for_tests()
        with mock_aws():
            client = boto3.client(
                "s3",
                aws_access_key_id="AKIA-TEST",
                aws_secret_access_key="SECRET-TEST",
                region_name="us-east-1",
            )
            client.create_bucket(Bucket="test-bucket")

            photo = PhotoFactory(
                event=EventFactory(slug="sc", brand_overlay="surf_city"),
                original_key="events/sc/originals/x.jpg",
            )
            key = generate_branded_original(photo, img_object=_solid(1600, 1000, (0, 0, 0)))

            assert key is not None
            assert key.endswith(".jpg")
            body = client.get_object(Bucket="test-bucket", Key=key)["Body"].read()
            im = Image.open(BytesIO(body))
            assert im.format == "JPEG"
            # FULL-RES: la descarga es el original a resolución completa (NO el
            # preview de 1200px). Un downscale accidental rompería la feature.
            assert im.size == (1600, 1000)
            rgb = im.convert("RGB")
            w, h = rgb.size
            assert _has_bright(rgb, 0, w // 3, h * 3 // 4, h)  # logo abajo-izq
            assert _has_bright(rgb, w * 2 // 3, w, h * 3 // 4, h)  # logo abajo-der
        storage_module.reset_default_storage_for_tests()


@pytest.mark.django_db
def test_download_key_selects_branded_only_for_branded_event() -> None:
    """`download_key()` = branded sólo si el evento tiene overlay Y hay branded_key;
    si no, el original limpio."""
    from tests.factories import EventFactory, PhotoFactory

    branded_evt = EventFactory(brand_overlay="surf_city")
    p_ok = PhotoFactory(event=branded_evt, original_key="o1", branded_key="b1")
    assert p_ok.download_key() == "b1"

    p_no_branded = PhotoFactory(event=branded_evt, original_key="o2", branded_key="")
    assert p_no_branded.download_key() == "o2"

    p_plain = PhotoFactory(
        event=EventFactory(brand_overlay=""), original_key="o3", branded_key="b3"
    )
    assert p_plain.download_key() == "o3"


# ---------------------------------------------------------------------------
# Template apilado (SÉPTIMO x CEP): 5 logos en dos filas abajo
# ---------------------------------------------------------------------------
SEPTIMO_ASSETS = (
    "SR2026_whiteP.png",
    "cep blanco.png",
    "GU_Secondary_White_Transparent.png",
    "LOGO TASU-01.png",
    "NUGO LOGO WHITE.webp",
)


def test_septimo_assets_exist_and_load_rgba() -> None:
    for name in SEPTIMO_ASSETS:
        assert (overlays.OVERLAY_DIR / name).exists(), f"falta el asset {name}"
        assert overlays._load_logo(name).mode == "RGBA"


def test_septimo_is_valid_template() -> None:
    assert overlays.is_valid_template("septimo_cep")


def test_septimo_pinta_dos_filas_abajo_y_no_toca_arriba() -> None:
    """Las dos filas caen en la mitad de abajo y la parte de arriba de la foto
    queda intacta (el degradado no debe subir hasta ahí)."""
    out = overlays.apply_brand_overlay(_solid(1067, 1600, (0, 0, 0)), "septimo_cep")
    assert out.mode == "RGB" and out.size == (1067, 1600)
    w, h = out.size
    # Fila de patrocinadores (la más baja): hay blanco a izquierda y a derecha.
    assert _has_bright(out, 0, w // 3, int(h * 0.90), h)
    assert _has_bright(out, w * 2 // 3, w, int(h * 0.90), h)
    # Fila de principales: blanco en el centro, más arriba.
    assert _has_bright(out, w // 4, w * 3 // 4, int(h * 0.82), int(h * 0.90))
    # La mitad de arriba de la foto no se toca.
    assert out.getpixel((w // 2, h // 4)) == (0, 0, 0)


def test_septimo_respeta_el_margen_lateral_de_instagram() -> None:
    """Ningún logo puede entrar en el 12% de cada lado: es lo que recorta IG al
    poner una foto vertical en una story."""
    out = overlays.apply_brand_overlay(_solid(1067, 1600, (0, 0, 0)), "septimo_cep")
    w, h = out.size
    borde = int(w * 0.11)  # un pelo adentro del margen configurado (12%)
    assert not _has_bright(out, 0, borde, 0, h)
    assert not _has_bright(out, w - borde, w, 0, h)


def test_septimo_funciona_horizontal_y_vertical() -> None:
    """En horizontal los logos escalan por el lado corto: mismo alto aparente,
    sin llenarse de logos gigantes."""
    vert = overlays.apply_brand_overlay(_solid(1067, 1600, (0, 0, 0)), "septimo_cep")
    horiz = overlays.apply_brand_overlay(_solid(1600, 1067, (0, 0, 0)), "septimo_cep")
    assert horiz.size == (1600, 1067)
    for img in (vert, horiz):
        w, h = img.size
        assert _has_bright(img, 0, w // 3, int(h * 0.90), h)
        assert _has_bright(img, w * 2 // 3, w, int(h * 0.90), h)


def test_septimo_no_se_sale_de_la_foto_en_tamanos_chicos() -> None:
    """Un thumbnail chico no debe romper ni desbordar (todo es proporcional)."""
    for size in ((400, 600), (600, 400), (200, 200)):
        out = overlays.apply_brand_overlay(_solid(*size, (0, 0, 0)), "septimo_cep")
        assert out.size == size


def test_septimo_horizontal_usa_una_sola_fila() -> None:
    """En apaisado los 5 logos van en una fila: entran a lo ancho y el degradado
    no se come media foto (con dos filas cubría casi la mitad del alto)."""
    gris = (60, 60, 60)
    out = overlays.apply_brand_overlay(_solid(1600, 1067, gris), "septimo_cep")
    w, h = out.size
    # Los 5 logos, repartidos: hay blanco a la izquierda, al centro y a la derecha.
    for x0, x1 in ((0, w // 4), (w * 3 // 8, w * 5 // 8), (w * 3 // 4, w)):
        assert _has_bright(out, x0, x1, int(h * 0.86), h), f"falta logo en {x0}-{x1}"
    # A media altura la foto sigue intacta: el degradado no llega hasta ahí.
    assert out.getpixel((w // 2, h // 2)) == gris


def test_los_logos_se_recortan_a_su_contenido() -> None:
    """Varios archivos vienen con relleno transparente alrededor (TASU: lienzo de
    369x369 con 287x183 de dibujo; NuGo: restos de antialias hasta el borde).
    Si no se recorta, al escalar por el alto se escala el lienzo y el logo sale
    hasta la mitad de chico de lo que pide el template."""
    casos = {
        "LOGO TASU-01.png": (287, 183),
        "NUGO LOGO WHITE.webp": (2293, 568),
        "SR2026_whiteP.png": (3853, 2493),
        "cep blanco.png": (1378, 471),
        "GU_Secondary_White_Transparent.png": (5983, 6128),  # este no tiene relleno
    }
    for nombre, esperado in casos.items():
        assert overlays._load_logo(nombre).size == esperado, nombre


def test_septimo_respeta_los_altos_pedidos_por_el_template() -> None:
    """El alto de cada fila tiene que ser el % del lado corto que pide el
    template (dentro de un pixel de redondeo), no el del lienzo del archivo."""
    cfg = overlays.TEMPLATES["septimo_cep"]
    assert isinstance(cfg, overlays.StackedTemplate)
    corto = 1067
    for fila in cfg.rows:
        piezas = overlays._row_pieces(fila, corto)
        for pieza, spec in zip(piezas, fila.logos, strict=True):
            esperado = round(corto * fila.h_pct * spec.scale)
            assert abs(pieza.height - esperado) <= 1, (spec.filename, pieza.height, esperado)


def test_fila_justificada_deja_el_logo_del_medio_en_el_eje() -> None:
    """En una fila justificada el primero va al margen izquierdo, el último al
    derecho y el del medio EN EL CENTRO de la foto. Repartir con huecos iguales
    lo corría casi un 9% del ancho, porque NuGo es mucho más ancho que GU."""
    cfg = overlays.TEMPLATES["septimo_cep"]
    assert isinstance(cfg, overlays.StackedTemplate)
    fila = cfg.rows[1]
    ancho = 1067
    piezas = overlays._row_pieces(fila, ancho)
    xs = overlays._row_positions(
        piezas,
        ancho,
        round(ancho * cfg.margin_x_pct),
        round(ancho * cfg.center_gap_pct),
        fila.spread,
    )
    margen = round(ancho * cfg.margin_x_pct)
    assert xs[0] == margen
    assert xs[-1] + piezas[-1].width == ancho - margen
    centro_medio = xs[1] + piezas[1].width // 2
    assert abs(centro_medio - ancho // 2) <= 1
