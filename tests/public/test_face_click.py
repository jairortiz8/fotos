"""Click en un retrato del visor: tiene que devolver LA PERSONA, no la foto.

El bug que documentan estos tests: la búsqueda usaba el vector de la cara
tocada y nada más. Una cara de perfil, chica o movida queda lejos —en el
espacio de vectores— de las frontales nítidas de la MISMA persona, así que
tocar un retrato de perfil devolvía tres fotos y tocar uno frontal devolvía
todas. Dos respuestas distintas para la misma persona según de qué foto entró
el corredor.

Los vectores de acá se construyen con geometría, no con caras reales: todos
viven en el plano (e0, e1), así que el coseno entre dos de ellos es exactamente
el que pedimos y los umbrales se pueden razonar a mano.

    perfil   = e0                       (el que toca el corredor)
    frontal  = 0.65 con perfil          → entra al promedio (umbral 0.62)
    lejana   = 0.45 con perfil          → NO la alcanzaba la búsqueda directa
                                          (umbral 0.48), pero está a 0.97 de
                                          `frontal`: es la misma persona.
"""

from __future__ import annotations

import math

import pytest
from django.test import Client
from django.urls import reverse

from apps.events.models import EventStatus
from apps.photos.models import FaceEmbedding
from apps.search.views import (
    FACE_CLICK_THRESHOLD,
    search_faces_by_similarity,
    search_faces_for_person,
)
from tests.factories import ApprovedPhotoFactory, EventFactory

DIM = 512


def _vec(coseno_con_e0: float) -> list[float]:
    """Vector unitario de 512 dims cuyo coseno con e0 es exactamente el pedido."""
    v = [0.0] * DIM
    v[0] = coseno_con_e0
    v[1] = math.sqrt(max(0.0, 1.0 - coseno_con_e0**2))
    return v


PERFIL = _vec(1.00)
FRONTAL = _vec(0.65)
LEJANA = _vec(0.45)


def _escena():
    """Un evento con tres fotos de la misma persona y una cara en cada una."""
    event = EventFactory(status=EventStatus.LIVE)
    caras = {}
    for nombre, vector in (("perfil", PERFIL), ("frontal", FRONTAL), ("lejana", LEJANA)):
        foto = ApprovedPhotoFactory(event=event)
        caras[nombre] = FaceEmbedding.objects.create(photo=foto, embedding=vector)
    return event, caras


@pytest.mark.django_db
def test_la_busqueda_directa_se_pierde_las_fotos_lejanas() -> None:
    """El bug, escrito. Esto NO es lo que queremos: es lo que pasaba."""
    event, caras = _escena()
    directas = search_faces_by_similarity(event, PERFIL, threshold=FACE_CLICK_THRESHOLD)
    ids = {f.id for f in directas}
    assert caras["frontal"].photo_id in ids
    assert caras["lejana"].photo_id not in ids, "0.45 < 0.48: por eso salían tres fotos"


@pytest.mark.django_db
def test_desde_una_cara_de_perfil_igual_aparecen_todas() -> None:
    """Promediando con las caras que sí son la misma persona, la lejana entra."""
    event, caras = _escena()
    fotos = search_faces_for_person(event, PERFIL, threshold=FACE_CLICK_THRESHOLD).fotos
    ids = {f.id for f in fotos}
    assert ids == {caras[n].photo_id for n in ("perfil", "frontal", "lejana")}


@pytest.mark.django_db
def test_entrar_por_cualquier_cara_da_el_mismo_resultado() -> None:
    """Lo que reportó Jair: la respuesta no puede depender de qué foto tocaste."""
    event, _caras = _escena()
    desde_perfil = {f.id for f in search_faces_for_person(event, PERFIL).fotos}
    desde_frontal = {f.id for f in search_faces_for_person(event, FRONTAL).fotos}
    assert desde_perfil == desde_frontal


@pytest.mark.django_db
def test_nunca_devuelve_menos_que_la_busqueda_directa() -> None:
    """La red de seguridad: unimos, no reemplazamos. Sólo puede agregar."""
    event, _ = _escena()
    for semilla in (PERFIL, FRONTAL, LEJANA):
        # El MISMO umbral en las dos, si no comparamos peras con manzanas.
        directas = {
            f.id for f in search_faces_by_similarity(event, semilla, threshold=FACE_CLICK_THRESHOLD)
        }
        ampliadas = {
            f.id
            for f in search_faces_for_person(event, semilla, threshold=FACE_CLICK_THRESHOLD).fotos
        }
        assert directas <= ampliadas


@pytest.mark.django_db
def test_una_cara_sola_no_se_expande() -> None:
    """Sin vecinas por encima del umbral estricto no hay nada que promediar:
    se cae a la búsqueda de siempre en vez de inventar un centroide de uno."""
    event = EventFactory(status=EventStatus.LIVE)
    foto = ApprovedPhotoFactory(event=event)
    FaceEmbedding.objects.create(photo=foto, embedding=PERFIL)
    otra = ApprovedPhotoFactory(event=event)
    FaceEmbedding.objects.create(photo=otra, embedding=_vec(0.10))  # otra persona

    fotos = search_faces_for_person(event, PERFIL).fotos
    assert {f.id for f in fotos} == {foto.id}


@pytest.mark.django_db
def test_el_click_en_el_visor_usa_la_busqueda_por_persona(client: Client) -> None:
    """De punta a punta: ?cara=<id de la cara de perfil> trae las tres fotos."""
    event, caras = _escena()
    r = client.get(reverse("events:gallery", args=[event.slug]), {"cara": caras["perfil"].id})
    assert r.status_code == 200
    assert r.context["is_face_search"] is True
    assert r.context["result_count"] == 3


# ---------------------------------------------------------------------------
# "Cara dudosa": distinguir al que sale poco del que salió mal
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_una_persona_que_sale_poco_no_se_marca_como_dudosa() -> None:
    """Tres fotos y nada más cerca: la respuesta es corta pero es la correcta.
    No hay que asustar al corredor con un aviso que no corresponde."""
    event = EventFactory(status=EventStatus.LIVE)
    for cos in (1.00, 0.50, 0.50):
        FaceEmbedding.objects.create(photo=ApprovedPhotoFactory(event=event), embedding=_vec(cos))

    r = search_faces_for_person(event, PERFIL)
    assert len(r.fotos) == 3
    assert r.cara_dudosa is False


@pytest.mark.django_db
def test_una_cara_mal_capturada_si_se_marca_como_dudosa() -> None:
    """Tres fotos al umbral, pero veinte apenas lo aflojás: eso no es una
    persona que sale poco, es un embedding malo. Aflojar el umbral traería a
    medio evento, así que no lo hacemos — lo avisamos."""
    event = EventFactory(status=EventStatus.LIVE)
    for cos in (1.00, 0.50, 0.50):
        FaceEmbedding.objects.create(photo=ApprovedPhotoFactory(event=event), embedding=_vec(cos))
    for _ in range(20):  # la población escondida, justo abajo del umbral
        FaceEmbedding.objects.create(photo=ApprovedPhotoFactory(event=event), embedding=_vec(0.42))

    r = search_faces_for_person(event, PERFIL)
    assert len(r.fotos) == 3, "no las traemos: a ese umbral ya sería medio evento"
    assert r.cara_dudosa is True


@pytest.mark.django_db
def test_una_persona_bien_fotografiada_nunca_es_dudosa() -> None:
    """El aviso es sólo para respuestas cortas. Con muchas fotos no se evalúa."""
    event = EventFactory(status=EventStatus.LIVE)
    for _ in range(12):
        FaceEmbedding.objects.create(photo=ApprovedPhotoFactory(event=event), embedding=_vec(0.95))
    r = search_faces_for_person(event, PERFIL)
    assert len(r.fotos) > 8
    assert r.cara_dudosa is False
