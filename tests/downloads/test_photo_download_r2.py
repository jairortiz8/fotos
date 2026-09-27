"""Descarga directo desde R2: la vista redirige (302) a una URL firmada en vez de
re-servir los bytes.

Por qué existe: Railway cobra el tráfico de salida y R2 no. En septiembre 2026
las descargas fueron ~190 GB, un tercio de la factura. La vista tiene que seguir
haciendo exactamente lo mismo que antes —validar, limitar, contar— y cambiar
SÓLO de dónde salen los bytes.

Lo que NO se puede probar acá, y quedó verificado contra el bucket real el
2026-09-27: que R2 respeta `response-content-disposition` y
`response-content-type` en una URL firmada (devolvió los dos headers, también con
`filename*` con acentos). Moto no sirve para eso: es un R2 de mentira.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.events.models import EventMetric, EventStatus, EventVisibility
from apps.ml.synthetic import synthetic_jpeg_bytes
from apps.photos import storage as storage_module
from apps.photos.models import PhotoStatus
from tests.factories import ApprovedPhotoFactory, EventFactory, PhotoFactory

BUCKET = "test-bucket"

UA_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"
)
UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
# El Safari de iPad pide la versión de escritorio y se presenta como Mac.
UA_IPAD_COMO_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)
UA_INSTAGRAM_ANDROID = (
    "Mozilla/5.0 (Linux; Android 13; moto g54) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/128.0.0.0 Mobile Safari/537.36 Instagram 347.0.0.36.89 Android"
)


@pytest.fixture
def r2(settings):  # type: ignore[no-untyped-def]
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    storage_module.reset_default_storage_for_tests()
    cache.clear()
    with mock_aws():
        client = boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        )
        client.create_bucket(Bucket=BUCKET)
        yield client
    storage_module.reset_default_storage_for_tests()
    cache.clear()


def _foto(r2, **extra):  # type: ignore[no-untyped-def]
    event = extra.pop("event", None) or EventFactory(
        status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC
    )
    key = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=key, Body=synthetic_jpeg_bytes("123"))
    extra.setdefault("original_filename", "DSC_1.jpg")
    return ApprovedPhotoFactory(event=event, original_key=key, **extra)


def _bajar(photo, ua: str = UA_ANDROID, **query):  # type: ignore[no-untyped-def]
    return Client().get(
        reverse("downloads:photo", kwargs={"photo_id": photo.id}),
        query,
        HTTP_USER_AGENT=ua,
    )


def _params(resp) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Los query params de la URL firmada a la que redirige."""
    return {k: v[0] for k, v in parse_qs(urlparse(resp["Location"]).query).items()}


# ---------------------------------------------------------------------------
# El interruptor
# ---------------------------------------------------------------------------
def test_por_defecto_esta_apagado(settings) -> None:  # type: ignore[no-untyped-def]
    """Desplegar esto NO cambia nada hasta que alguien prende la variable. Si
    este test falla, alguien cambió el default: eso activa R2 en el próximo deploy."""
    assert settings.PHOTO_DOWNLOAD_R2_DIRECT == "off"


@pytest.mark.django_db
def test_apagado_sigue_siendo_proxy_aunque_sea_android(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "off"
    resp = _bajar(_foto(r2))
    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")


@pytest.mark.django_db
def test_un_valor_desconocido_cuenta_como_apagado(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "si"  # typo en Railway: no puede prender nada
    assert _bajar(_foto(r2)).status_code == 200


# ---------------------------------------------------------------------------
# non_apple: Android a R2, Apple sigue por proxy
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_android_va_directo_a_r2(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "non_apple"
    resp = _bajar(_foto(r2))
    assert resp.status_code == 302
    p = _params(resp)
    assert p["response-content-disposition"] == 'attachment; filename="DSC_1.jpg"'
    assert p["response-content-type"] == "image/jpeg"
    assert urlparse(resp["Location"]).path.endswith("/events/e/originals/foto.jpg")


@pytest.mark.django_db
def test_la_url_vence_en_15_minutos_como_maximo(r2, settings) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3: originales sólo por URL firmada de 15 min como máximo."""
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "non_apple"
    assert int(_params(_bajar(_foto(r2)))["X-Amz-Expires"]) <= 900


@pytest.mark.django_db
def test_el_redirect_no_se_cachea(r2, settings) -> None:  # type: ignore[no-untyped-def]
    """Un redirect cacheado mandaría a alguien a una URL ya vencida (403 de R2)."""
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "non_apple"
    cc = _bajar(_foto(r2))["Cache-Control"]
    assert "no-store" in cc or "no-cache" in cc


@pytest.mark.django_db
@pytest.mark.parametrize("ua", [UA_IPHONE, UA_IPAD_COMO_MAC])
def test_apple_sigue_por_proxy(r2, settings, ua: str) -> None:  # type: ignore[no-untyped-def]
    """En junio un redirect a R2 se abrió como página en un iPhone. Hasta probarlo
    en un equipo de verdad, Apple no cambia."""
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "non_apple"
    resp = _bajar(_foto(r2), ua=ua)
    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment")
    assert resp["Content-Type"] == "image/jpeg"


@pytest.mark.django_db
def test_el_navegador_de_instagram_en_android_va_a_r2(r2, settings) -> None:  # type: ignore[no-untyped-def]
    """El WebView de Android le pasa la URL final a la app para que la baje sin
    cookies: una URL firmada sirve igual que el proxy, y evita que Django reciba
    el pedido dos veces."""
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "non_apple"
    assert _bajar(_foto(r2), ua=UA_INSTAGRAM_ANDROID).status_code == 302


@pytest.mark.django_db
def test_all_manda_a_r2_tambien_a_apple(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "all"
    assert _bajar(_foto(r2), ua=UA_IPHONE).status_code == 302


# ---------------------------------------------------------------------------
# ?via= para probar en producción sin tocar la variable
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_via_r2_fuerza_el_redirect_aunque_este_apagado(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "off"
    assert _bajar(_foto(r2), ua=UA_IPHONE, via="r2").status_code == 302


@pytest.mark.django_db
def test_via_proxy_fuerza_el_proxy_aunque_este_prendido(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "all"
    assert _bajar(_foto(r2), via="proxy").status_code == 200


# ---------------------------------------------------------------------------
# Lo que NO puede cambiar: conteo, límite, permisos, versión con logos
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_por_r2_se_cuenta_igual_que_por_proxy(r2, settings) -> None:  # type: ignore[no-untyped-def]
    """El dashboard (tarjeta de descargas y curva por hora) no puede enterarse
    de por dónde salió la foto."""
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "non_apple"
    photo = _foto(r2)
    event = photo.event

    assert _bajar(photo).status_code == 302
    photo.refresh_from_db()
    event.refresh_from_db()
    assert photo.download_count == 1
    assert event.download_count == 1
    assert (
        EventMetric.objects.filter(event=event, metric=EventMetric.Metric.DOWNLOAD)
        .values_list("count", flat=True)
        .first()
        == 1
    )


@pytest.mark.django_db
def test_el_limite_corta_antes_del_redirect(r2, settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Si el límite se aplicara después, cualquiera podría juntar URLs firmadas
    de un evento entero sin topar nunca."""
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "non_apple"
    monkeypatch.setattr("apps.downloads.views.check_photo_download_rate_limit", lambda r: False)
    photo = _foto(r2)

    resp = _bajar(photo)
    assert resp.status_code == 429
    assert "Location" not in resp
    photo.refresh_from_db()
    assert photo.download_count == 0


@pytest.mark.django_db
def test_foto_no_aprobada_da_404_tambien_por_r2(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "all"
    photo = PhotoFactory(status=PhotoStatus.PENDING_REVIEW)
    assert _bajar(photo).status_code == 404


@pytest.mark.django_db
def test_evento_privado_da_404_tambien_por_r2(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "all"
    event = EventFactory(status=EventStatus.LIVE, visibility=EventVisibility.PRIVATE)
    assert _bajar(_foto(r2, event=event)).status_code == 404


@pytest.mark.django_db
def test_evento_con_logos_redirige_a_la_version_con_logos(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "all"
    event = EventFactory(
        status=EventStatus.LIVE, visibility=EventVisibility.PUBLIC, brand_overlay="surf_city"
    )
    photo = _foto(r2, event=event, branded_key="events/e/branded/foto.jpg")
    assert urlparse(_bajar(photo)["Location"]).path.endswith("/events/e/branded/foto.jpg")


@pytest.mark.django_db
def test_el_nombre_lleva_extension_jpg_tambien_por_r2(r2, settings) -> None:  # type: ignore[no-untyped-def]
    settings.PHOTO_DOWNLOAD_R2_DIRECT = "all"
    photo = _foto(r2, original_filename="sin_extension")
    assert _params(_bajar(photo))["response-content-disposition"].endswith('"sin_extension.jpg"')


# ---------------------------------------------------------------------------
# El header del nombre, igual que el de Django
# ---------------------------------------------------------------------------
def test_nombre_con_acentos_usa_filename_estrella(r2) -> None:  # type: ignore[no-untyped-def]
    """Hoy los nombres son ASCII (sanitize_filename), pero si alguno no lo es, el
    header no se puede romper: va en `filename*` como hace Django."""
    url = storage_module.default_storage().get_signed_url(
        "k.jpg", download_filename="Foto Maratón.jpg"
    )
    cd = parse_qs(urlparse(url).query)["response-content-disposition"][0]
    assert cd == "attachment; filename*=utf-8''Foto%20Marat%C3%B3n.jpg"


def test_sin_nombre_no_pide_attachment(r2) -> None:  # type: ignore[no-untyped-def]
    """Las URLs de previews y thumbnails no se tocan: se siguen mostrando."""
    url = storage_module.default_storage().get_signed_url("k.jpg")
    q = parse_qs(urlparse(url).query)
    assert "response-content-disposition" not in q
    assert "response-content-type" not in q
