"""Visor de caras: filtro de calidad, recorte, avatar y búsqueda por cara."""

from __future__ import annotations

from io import BytesIO

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws
from PIL import Image

from apps.events.models import EventStatus
from apps.photos import storage as storage_module
from apps.photos.faces import face_size_px, generate_avatars_for_photo, is_avatar_sized
from apps.photos.imaging import FaceTooBlurryError, _square_face_box, generate_face_avatar
from apps.photos.models import FaceEmbedding
from tests.factories import ApprovedPhotoFactory, EventFactory

BUCKET = "test-bucket"


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


def _sharp_photo_bytes(w: int = 900, h: int = 600) -> bytes:
    """JPEG con bordes duros (alto contraste) → pasa el umbral de nitidez."""
    img = Image.new("RGB", (w, h), "white")
    px = img.load()
    assert px is not None
    for x in range(w):
        for y in range(h):
            if (x // 6 + y // 6) % 2 == 0:
                px[x, y] = (10, 10, 10)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _flat_photo_bytes(w: int = 900, h: int = 600) -> bytes:
    """JPEG liso (sin detalle) → NO pasa el umbral de nitidez."""
    buf = BytesIO()
    Image.new("RGB", (w, h), (128, 128, 130)).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# --- filtro de tamaño -------------------------------------------------------
def test_face_size_px_uses_larger_side() -> None:
    assert face_size_px({"x1": 0, "y1": 0, "x2": 100, "y2": 40}) == 100
    assert face_size_px({}) == 0.0
    assert face_size_px(None) == 0.0


def test_is_avatar_sized_rejects_small_faces() -> None:
    """Una cara del fondo (chiquita) no se convierte en avatar."""
    big = {"x1": 0, "y1": 0, "x2": 200, "y2": 200}  # > 130px -> entra
    small = {"x1": 0, "y1": 0, "x2": 100, "y2": 100}  # < 130px (fondo) -> fuera
    assert is_avatar_sized(big) is True
    assert is_avatar_sized(small) is False


# --- recorte ----------------------------------------------------------------
def test_square_face_box_is_square_and_inside_image() -> None:
    left, top, right, bottom = _square_face_box({"x1": 10, "y1": 20, "x2": 60, "y2": 90}, 800, 600)
    assert right - left == bottom - top  # cuadrado
    assert left >= 0 and top >= 0
    assert right <= 800 and bottom <= 600


def test_square_face_box_clamps_face_at_the_edge() -> None:
    """Cara pegada al borde: la caja se corre adentro en vez de salirse."""
    left, top, right, bottom = _square_face_box({"x1": 0, "y1": 0, "x2": 40, "y2": 40}, 300, 300)
    assert left >= 0 and top >= 0
    assert right <= 300 and bottom <= 300


def test_generate_face_avatar_returns_square_webp() -> None:
    data = generate_face_avatar(_sharp_photo_bytes(), {"x1": 100, "y1": 100, "x2": 300, "y2": 300})
    img = Image.open(BytesIO(data))
    assert img.format == "WEBP"
    assert img.width == img.height == 160


def test_generate_face_avatar_rejects_blurry_crop() -> None:
    """Una cara sin detalle (fondo desenfocado) no genera avatar."""
    with pytest.raises(FaceTooBlurryError):
        generate_face_avatar(_flat_photo_bytes(), {"x1": 100, "y1": 100, "x2": 300, "y2": 300})


# --- batch por foto ---------------------------------------------------------
@pytest.mark.django_db
def test_generate_avatars_for_photo_skips_small_and_keeps_big(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)

    big = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    small = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.2] * 512, bbox={"x1": 10, "y1": 10, "x2": 40, "y2": 40}
    )

    stats = generate_avatars_for_photo(photo)
    assert stats["generated"] == 1
    assert stats["too_small"] == 1

    big.refresh_from_db()
    small.refresh_from_db()
    assert big.avatar_key != ""
    assert small.avatar_key == ""


@pytest.mark.django_db
def test_generate_avatars_for_photo_is_idempotent(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )

    assert generate_avatars_for_photo(photo)["generated"] == 1
    assert generate_avatars_for_photo(photo)["generated"] == 0  # ya estaba


# --- vistas -----------------------------------------------------------------
@pytest.mark.django_db
def test_face_avatar_view_serves_webp(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    face = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    generate_avatars_for_photo(photo)

    resp = Client().get(
        reverse("events:face_avatar", kwargs={"slug": event.slug, "face_id": face.id})
    )
    assert resp.status_code == 200
    assert resp["Content-Type"] == "image/webp"
    assert "max-age" in resp["Cache-Control"]


@pytest.mark.django_db
def test_face_avatar_view_404_without_avatar(r2) -> None:  # type: ignore[no-untyped-def]
    """Una cara que no calificó (sin avatar_key) no se sirve."""
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, original_key="events/e/originals/x.jpg")
    face = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 0, "y1": 0, "x2": 20, "y2": 20}
    )
    resp = Client().get(
        reverse("events:face_avatar", kwargs={"slug": event.slug, "face_id": face.id})
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_lightbox_shows_visor_only_for_faces_with_avatar(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    big = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    small = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.2] * 512, bbox={"x1": 5, "y1": 5, "x2": 30, "y2": 30}
    )
    generate_avatars_for_photo(photo)

    resp = Client().get(
        reverse("events:lightbox", kwargs={"slug": event.slug, "photo_id": photo.id})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?cara={big.id}" in body
    assert f"?cara={small.id}" not in body  # la chica no entra al visor


@pytest.mark.django_db
def test_gallery_face_search_returns_that_person(r2) -> None:  # type: ignore[no-untyped-def]
    """?cara=<id> devuelve las fotos parecidas usando el embedding guardado."""
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    other = ApprovedPhotoFactory(event=event, original_key="events/e/originals/otra.jpg")

    vec = [0.0] * 512
    vec[0] = 1.0
    face = FaceEmbedding.objects.create(
        photo=photo, embedding=vec, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    # Misma persona en otra foto (vector idéntico) → tiene que aparecer.
    FaceEmbedding.objects.create(
        photo=other, embedding=vec, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )
    # Persona distinta (vector ortogonal) → NO tiene que aparecer.
    far = [0.0] * 512
    far[1] = 1.0
    third = ApprovedPhotoFactory(event=event, original_key="events/e/originals/tercera.jpg")
    FaceEmbedding.objects.create(
        photo=third, embedding=far, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )

    resp = Client().get(
        reverse("events:gallery", kwargs={"slug": event.slug}), {"cara": str(face.id)}
    )
    assert resp.status_code == 200
    ids = {p.id for p in resp.context["search_photos"]}
    assert {photo.id, other.id} <= ids
    assert third.id not in ids


# --- Garantía de cobertura --------------------------------------------------
@pytest.mark.django_db
def test_caras_medianas_entran_sin_pedirles_nitidez(r2) -> None:  # type: ignore[no-untyped-def]
    """Entre el piso (50px) y el umbral (130px) las caras SÍ se ofrecen.

    Antes acá sólo entraba la más grande, por el respaldo. En una foto grupal
    eso dejaba a todos los demás sin forma de buscarse.
    """
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)

    chica = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 10, "y1": 10, "x2": 60, "y2": 60}
    )
    mediana = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.2] * 512, bbox={"x1": 100, "y1": 100, "x2": 220, "y2": 220}
    )

    stats = generate_avatars_for_photo(photo)
    assert stats["generated"] == 2
    assert stats["fallback"] == 0  # no hizo falta el respaldo

    chica.refresh_from_db()
    mediana.refresh_from_db()
    assert mediana.avatar_key != ""
    assert chica.avatar_key != ""


@pytest.mark.django_db
def test_foto_grupal_ofrece_a_todas_las_personas(r2) -> None:  # type: ignore[no-untyped-def]
    """Regresión del social run de Garmin (2026-08).

    En una foto de grupo cada cara mide ~60px: ninguna llegaba a 130px y la
    foto terminaba ofreciendo UNA sola persona. Las demás no tenían forma de
    encontrarse en esa foto.
    """
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/grupal.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)

    for i in range(8):  # 8 caras de 60px, en fila
        FaceEmbedding.objects.create(
            photo=photo,
            embedding=[0.1 * i] * 512,
            bbox={"x1": 20 + i * 100, "y1": 200, "x2": 80 + i * 100, "y2": 260},
        )

    stats = generate_avatars_for_photo(photo)
    assert stats["generated"] == 8, "cada persona del grupo tiene que ser clickeable"
    assert stats["fallback"] == 0
    assert photo.face_embeddings.exclude(avatar_key="").count() == 8


@pytest.mark.django_db
def test_caras_bajo_el_piso_caen_al_respaldo(r2) -> None:  # type: ignore[no-untyped-def]
    """Por debajo del piso (50px) la cara ya no se distingue: sólo la mayor."""
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/lejos.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)

    diminuta = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 10, "y1": 10, "x2": 32, "y2": 32}
    )
    mayor = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.2] * 512, bbox={"x1": 100, "y1": 100, "x2": 140, "y2": 140}
    )

    stats = generate_avatars_for_photo(photo)
    assert stats["generated"] == 1
    assert stats["fallback"] == 1

    diminuta.refresh_from_db()
    mayor.refresh_from_db()
    assert mayor.avatar_key != ""
    assert diminuta.avatar_key == ""


@pytest.mark.django_db
def test_blurry_only_photo_still_gets_one_avatar(r2) -> None:  # type: ignore[no-untyped-def]
    """Idem cuando la cara es grande pero no llega al umbral de nitidez."""
    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/foto.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_flat_photo_bytes())  # sin detalle
    photo = ApprovedPhotoFactory(event=event, original_key=okey)
    face = FaceEmbedding.objects.create(
        photo=photo, embedding=[0.1] * 512, bbox={"x1": 100, "y1": 100, "x2": 300, "y2": 300}
    )

    stats = generate_avatars_for_photo(photo)
    assert stats["blurry"] == 1  # falló el filtro...
    assert stats["fallback"] == 1  # ...pero el respaldo la rescató
    face.refresh_from_db()
    assert face.avatar_key != ""


@pytest.mark.django_db
def test_photo_without_faces_generates_nothing(r2) -> None:  # type: ignore[no-untyped-def]
    """Una foto sin caras detectadas no genera avatar ni rompe."""
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event, original_key="events/e/originals/vacia.jpg")
    stats = generate_avatars_for_photo(photo)
    assert stats["generated"] == 0
    assert stats["fallback"] == 0


# --- Recall del click en la cara -------------------------------------------
def test_face_click_no_usa_el_tope_de_50() -> None:
    """El click en una cara devuelve MUCHAS más de 50.

    Medido en prod: hay corredores con 100+ fotos. Con el tope de 50 del selfie,
    el "ver todas las fotos de esta persona" mentía. Este test fija que el click
    tenga su propio tope, bien por encima.
    """
    from apps.search.views import FACE_CLICK_MAX_RESULTS, MAX_SELFIE_RESULTS

    assert FACE_CLICK_MAX_RESULTS >= 300
    assert FACE_CLICK_MAX_RESULTS > MAX_SELFIE_RESULTS


def test_umbral_del_click_prioriza_encontrar_todas() -> None:
    """El click en una cara usa un umbral MÁS PERMISIVO que el selfie.

    Con 0.62 se perdía ~1 de cada 3 apariciones reales (misma persona de lejos
    o de perfil). Al ser "mostrame todas mis fotos", una de más molesta menos
    que una propia que falta.
    """
    from apps.search.views import FACE_CLICK_THRESHOLD, SIMILARITY_THRESHOLD

    assert FACE_CLICK_THRESHOLD < SIMILARITY_THRESHOLD
    assert FACE_CLICK_THRESHOLD >= 0.40, "demasiado permisivo: entrarían desconocidos"


@pytest.mark.django_db
def test_lightbox_no_apila_caras_ni_dorsales_en_varias_filas(r2) -> None:  # type: ignore[no-untyped-def]
    """Regresión: con muchas caras la barra crecía y tapaba la foto.

    En una foto de 18 personas el visor se partía en tres filas y los chips de
    dorsal en cuatro; la barra inferior (absolute bottom-0) se comía la imagen.
    La cura es que ambas tiras sean UNA sola fila con scroll lateral.
    """
    from apps.photos.models import Bib

    event = EventFactory(status=EventStatus.LIVE)
    okey = "events/e/originals/multitud.jpg"
    r2.put_object(Bucket=BUCKET, Key=okey, Body=_sharp_photo_bytes())
    photo = ApprovedPhotoFactory(event=event, original_key=okey)

    for i in range(10):  # muchas caras
        FaceEmbedding.objects.create(
            photo=photo,
            embedding=[0.01 * i] * 512,
            bbox={"x1": 20 + i * 80, "y1": 150, "x2": 90 + i * 80, "y2": 220},
        )
    for n in range(7):  # y muchos dorsales
        Bib.objects.create(photo=photo, number=f"10{n}", confidence=0.9, source="ocr_gemini")
    generate_avatars_for_photo(photo)

    body = (
        Client()
        .get(reverse("events:lightbox", kwargs={"slug": event.slug, "photo_id": photo.id}))
        .content.decode()
    )
    # Los dorsales van en una fila que NO se parte.
    assert "flex flex-nowrap gap-1.5" in body
    assert "flex flex-wrap gap-1.5" not in body
    # Y la foto reserva el alto de la barra, así no queda tapada.
    assert "pb-40" in body
