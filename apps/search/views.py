"""Búsqueda por selfie (reconocimiento facial).

PRIVACIDAD (CLAUDE.md §3): el selfie del usuario se procesa EN MEMORIA durante
el request y se descarta. El embedding NUNCA se persiste ni pasa por Celery/Redis.
Esta vista es 100% síncrona por diseño (ADR 0006).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F, Min
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from pgvector.django import CosineDistance

from apps.core.utils import check_selfie_rate_limit, get_client_ip, hash_ip
from apps.events.metrics import Metric, record_event_metric
from apps.events.models import Event, EventVisibility
from apps.photos.models import Photo, PhotoStatus, bibs_visibles

logger = logging.getLogger(__name__)

# Umbral de similitud coseno (ADR 0006). Ajustable con `tune_threshold`.
SIMILARITY_THRESHOLD = 0.55
# Clave de sesión donde viven los resultados del selfie (solo ids + %).
SELFIE_RESULTS_KEY = "selfie_results"
# Click en una cara del visor.
# MEDIDO contra datos reales de Surf City (2026-08), usando el dorsal como
# verdad de referencia sobre en qué fotos está cada corredor:
#     umbral   0.62    0.55    0.45    0.35
#     recall    42%     51%     55%     61%
# Con 0.62 se perdía ~1 de cada 3 apariciones REALES: la misma persona de
# lejos, de perfil o con otra luz queda apenas por debajo del corte. Bajado a
# 0.48, que recupera la mayor parte sin irse al extremo permisivo. Es la
# función "mostrame todas mis fotos": una foto de más molesta mucho menos que
# una propia que falta.
FACE_CLICK_THRESHOLD = 0.48
MAX_SELFIE_RESULTS = 50
# El click en una cara NO usa el tope de 50: un corredor bien fotografiado
# aparece en 100+ fotos y cortarle a 50 contradice el "todas tus fotos".
# La consulta es un índice HNSW, así que subir el tope no la encarece.
FACE_CLICK_MAX_RESULTS = 400
# Expansión del click en una cara (ver `search_faces_for_person`).
# EXPAND: sólo caras casi con certeza de la misma persona entran al promedio.
# A 0.62 el falso positivo es raro; bajarlo trae más fotos pero también más
# riesgo de mezclar dos personas parecidas.
FACE_EXPAND_THRESHOLD = 0.62
FACE_EXPAND_MAX_SEEDS = 8
# Detección de "cara dudosa" (ver `search_faces_for_person`). Medido contra dos
# eventos reales: una persona que de verdad sale poco tiene 4 fotos al umbral y
# 5 si lo aflojás mucho; una cara mal capturada tiene 3 al umbral y 74 al
# aflojarlo — y 74 es, en ese evento, la MEDIANA. O sea: cuando encuentra algo
# ya está matcheando a medio evento. No hay umbral que rescate esa cara, así que
# no lo intentamos: lo detectamos y se lo decimos al corredor.
FACE_WEAK_MAX_PHOTOS = 8  # por debajo de esto la respuesta es sospechosamente corta
FACE_WEAK_LOOSE = 0.40  # banda floja donde se ve si hay población escondida
FACE_WEAK_FACTOR = 4.0  # cuánto tiene que crecer de una banda a la otra
FACE_NEIGHBOURS = 400  # vecinas que traemos para medir las bandas
MAX_SELFIE_BYTES = 10 * 1024 * 1024  # 10 MB

# Cortes de confianza para agrupar resultados en la UI.
HIGH_CONFIDENCE = 0.80
MED_CONFIDENCE = 0.60


def _face_unavailable(request: HttpRequest, event: Event | None, *, mode: str) -> HttpResponse:
    """Respuesta amable cuando la búsqueda facial está apagada (FACE_SEARCH_ENABLED).

    `mode`: "search" (buscar por selfie) o "delete" (borrar mis datos).
    No carga el modelo — es seguro de servir en el dyno de 1GB.
    """
    return render(
        request,
        "public/face_unavailable.html",
        {"event": event, "mode": mode},
        status=503,
    )


@method_decorator(csrf_exempt, name="dispatch")
class SelfieSearchView(View):
    """GET: formulario de selfie. POST: procesa y devuelve coincidencias."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)
        if not self._can_search(event):
            raise Http404
        if not settings.FACE_SEARCH_ENABLED:
            return _face_unavailable(request, event, mode="search")
        return render(
            request,
            "public/selfie_search.html",
            {
                "event": event,
                "approved_count": event.photos.filter(status=PhotoStatus.APPROVED).count(),
            },
        )

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)
        if not self._can_search(event):
            raise Http404

        # Cortamos ANTES de cargar buffalo_l: en prod (dyno 1GB) cargar el
        # modelo OOM-killea el worker. El flag lo mantiene apagado hasta resolver
        # la RAM. Local/dev queda en True.
        if not settings.FACE_SEARCH_ENABLED:
            return _face_unavailable(request, event, mode="search")

        if not check_selfie_rate_limit(request):
            return render(request, "public/rate_limited.html", {"event": event}, status=429)

        selfie = request.FILES.get("selfie")
        if not selfie:
            return JsonResponse({"error": "no_selfie"}, status=400)
        if selfie.size and selfie.size > MAX_SELFIE_BYTES:
            return JsonResponse({"error": "file_too_large", "max_mb": 10}, status=400)

        # --- Procesamiento EN MEMORIA — el embedding nunca se persiste ---
        from apps.ml.face_recognition import (
            InvalidImageError,
            MultipleFacesDetectedError,
            NoFaceDetectedError,
            embedding_from_bytes,
        )

        try:
            query_embedding = embedding_from_bytes(selfie.read())
        except NoFaceDetectedError:
            return render(request, "public/selfie_no_face.html", {"event": event})
        except MultipleFacesDetectedError:
            return render(request, "public/selfie_multiple_faces.html", {"event": event})
        except InvalidImageError:
            return JsonResponse({"error": "invalid_format"}, status=400)

        matches = search_faces_by_similarity(event, query_embedding.tolist())

        # Actualizar retención de los matches (last_matched_at).
        if matches:
            from apps.photos.models import FaceEmbedding

            FaceEmbedding.objects.filter(photo_id__in=[m.id for m in matches]).update(
                last_matched_at=timezone.now(),
                match_count=F("match_count") + 1,
            )
            event.__class__.objects.filter(id=event.id).update(search_count=F("search_count") + 1)
            record_event_metric(event.id, Metric.SEARCH)

        # Log anonimizado (sin el embedding ni la IP cruda).
        logger.info(
            "selfie_search event=%s matches=%d ip_hash=%s",
            event.slug,
            len(matches),
            hash_ip(get_client_ip(request))[:12],
        )

        # IMPORTANTE: query_embedding sale de scope al terminar el request.
        if not matches:
            return render(request, "public/selfie_no_results.html", {"event": event})

        # Los resultados se guardan en la SESIÓN y se redirige a una URL GET.
        #
        # Antes esta vista renderizaba los resultados directo en la respuesta del
        # POST. Eso dejaba las coincidencias sin URL: al abrir una foto y volver,
        # el corredor perdía TODO y tenía que sacarse el selfie de nuevo; y
        # recargar la página hacía que el celular pidiera reenviar el formulario.
        #
        # PRIVACIDAD (ADR 0006): en la sesión van SOLO ids de foto y el
        # porcentaje de similitud. El selfie y el embedding NO se guardan: siguen
        # viviendo y muriendo dentro de este request.
        request.session[SELFIE_RESULTS_KEY] = {
            "slug": event.slug,
            "at": timezone.now().isoformat(),
            "matches": [{"id": m.id, "sim": int(getattr(m, "similarity", 0))} for m in matches],
        }
        return redirect("events:selfie_results", slug=event.slug)

    @staticmethod
    def _can_search(event: Event) -> bool:
        if event.visibility == EventVisibility.PRIVATE:
            return False
        return event.is_searchable()


class SelfieResultsView(View):
    """Resultados del selfie en una URL GET propia, leídos de la sesión.

    Existe para que las coincidencias tengan dirección: así el corredor puede
    entrar a una foto y volver sin perderlas, recargar sin reenviar el
    formulario, y usar el botón de atrás del celular."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)
        if not SelfieSearchView._can_search(event):
            raise Http404

        guardado = request.session.get(SELFIE_RESULTS_KEY) or {}
        if guardado.get("slug") != event.slug or not guardado.get("matches"):
            return redirect("events:selfie_search", slug=event.slug)

        if _resultados_vencidos(guardado.get("at")):
            request.session.pop(SELFIE_RESULTS_KEY, None)
            return redirect("events:selfie_search", slug=event.slug)

        sims = {int(m["id"]): int(m["sim"]) for m in guardado["matches"]}
        orden = [int(m["id"]) for m in guardado["matches"]]
        encontradas = {
            p.id: p
            for p in Photo.objects.filter(
                id__in=orden, event=event, status=PhotoStatus.APPROVED
            ).prefetch_related(bibs_visibles())
        }
        # Se respeta el orden por similitud que tenía la búsqueda, y se saltean
        # las fotos que ya no estén aprobadas.
        matches = []
        for pid in orden:
            foto = encontradas.get(pid)
            if foto is None:
                continue
            foto.similarity = sims[pid]  # type: ignore[attr-defined]
            matches.append(foto)
        if not matches:
            return redirect("events:selfie_search", slug=event.slug)

        def _sim(photo: Photo) -> int:
            return int(getattr(photo, "similarity", 0))

        return render(
            request,
            "public/selfie_results.html",
            {
                "event": event,
                "matches": matches,
                "high_matches": [m for m in matches if _sim(m) >= HIGH_CONFIDENCE * 100],
                "med_matches": [
                    m for m in matches if MED_CONFIDENCE * 100 <= _sim(m) < HIGH_CONFIDENCE * 100
                ],
                "low_matches": [m for m in matches if _sim(m) < MED_CONFIDENCE * 100],
                "match_count": len(matches),
                # Para que el lightbox sepa a dónde volver.
                "volver": request.get_full_path(),
            },
        )


def _resultados_vencidos(marca: str | None, *, minutos: int = 60) -> bool:
    """True si los resultados guardados en la sesión ya son viejos."""
    if not marca:
        return True
    try:
        cuando = datetime.fromisoformat(marca)
    except ValueError:
        return True
    return timezone.now() - cuando > timedelta(minutes=minutos)


# ---------------------------------------------------------------------------
# Matching con pgvector
# ---------------------------------------------------------------------------
def search_faces_by_similarity(
    event: Event,
    query_embedding: list[float],
    *,
    threshold: float = SIMILARITY_THRESHOLD,
    limit: int = MAX_SELFIE_RESULTS,
) -> list[Photo]:
    """Devuelve fotos aprobadas ordenadas por similitud coseno (desc).

    cosine_distance = 1 - cosine_similarity, así que filtramos por
    `distance <= 1 - threshold` y ordenamos ascendente por distancia.
    """
    max_distance = 1 - threshold
    results: list[Photo] = list(
        Photo.objects.filter(event=event, status=PhotoStatus.APPROVED)
        .annotate(min_distance=Min(CosineDistance("face_embeddings__embedding", query_embedding)))
        .filter(min_distance__isnull=False, min_distance__lte=max_distance)
        .order_by("min_distance")
        .prefetch_related(bibs_visibles())[:limit]
    )
    for photo in results:
        # `min_distance` y `similarity` son atributos anotados/dinámicos.
        photo.similarity = round((1 - photo.min_distance) * 100)  # type: ignore[attr-defined]
    return results


def _centroide(vectores: list[list[float]]) -> list[float]:
    """Promedio normalizado de varios embeddings (todos vienen normalizados L2)."""
    dim = len(vectores[0])
    suma = [0.0] * dim
    for v in vectores:
        for i, x in enumerate(v):
            suma[i] += x
    norma = math.sqrt(sum(x * x for x in suma)) or 1.0
    return [x / norma for x in suma]


@dataclass(frozen=True)
class ResultadoPorCara:
    """Lo que devuelve el click en un retrato.

    `cara_dudosa` no es un detalle técnico: es lo que le permite a la pantalla
    decirle al corredor "puede que falten fotos, probá con otro retrato" en vez
    de mostrarle tres fotos como si fueran todas.
    """

    fotos: list[Photo]
    cara_dudosa: bool


def search_faces_for_person(
    event: Event,
    seed_embedding: list[float],
    *,
    threshold: float = FACE_CLICK_THRESHOLD,
    limit: int = FACE_CLICK_MAX_RESULTS,
) -> ResultadoPorCara:
    """Las fotos de la PERSONA de esa cara, no las parecidas a esa FOTO.

    Buscar con una sola cara es inestable. El vector de una cara de perfil,
    chica o movida queda lejos de las frontales nítidas de la MISMA persona, así
    que tocar un retrato de perfil devolvía tres fotos y tocar uno frontal
    devolvía todas.

    La cara tocada es la SEMILLA: con ella buscamos las caras que son casi con
    certeza la misma persona (umbral estricto), promediamos esos vectores y
    volvemos a buscar con el promedio, que representa a la persona mucho mejor
    que cualquier foto suelta. El resultado se UNE con el de la búsqueda
    directa, así que esto nunca devuelve MENOS que antes: sólo agrega.

    Y cuando la semilla es mala de entrada —no tiene con qué promediarse— al
    menos lo detectamos, mirando cómo crece la población al aflojar el umbral.
    Bajar el umbral NO es la salida: a 0.40 una cara mala matchea la mediana del
    evento entero. Lo único honesto es avisar.
    """
    from apps.photos.models import FaceEmbedding

    directas = search_faces_by_similarity(event, seed_embedding, threshold=threshold, limit=limit)

    caras = FaceEmbedding.objects.filter(
        photo__event=event, photo__status=PhotoStatus.APPROVED
    ).annotate(distancia=CosineDistance("embedding", seed_embedding))

    # Las bandas: sólo distancias, sin traer 400 vectores de 512 dimensiones.
    bandas = list(
        caras.order_by("distancia").values_list("photo_id", "distancia")[:FACE_NEIGHBOURS]
    )

    semillas = list(
        caras.filter(distancia__lte=1 - FACE_EXPAND_THRESHOLD)
        .order_by("distancia")
        .values_list("embedding", flat=True)[:FACE_EXPAND_MAX_SEEDS]
    )

    fotos = directas
    # Una sola semilla (ella misma) = no hay nada que promediar.
    if len(semillas) >= 2:
        centro = _centroide([[float(x) for x in v] for v in semillas])
        ampliadas = search_faces_by_similarity(event, centro, threshold=threshold, limit=limit)
        fotos = _unir(directas, ampliadas, limit)

    return ResultadoPorCara(fotos=fotos, cara_dudosa=_es_dudosa(fotos, bandas, threshold))


def _sim(foto: Photo) -> int:
    """`similarity` lo pone la query a mano, no es un campo del modelo."""
    return int(getattr(foto, "similarity", 0))


def _unir(a: list[Photo], b: list[Photo], limit: int) -> list[Photo]:
    """Une dos resultados quedándose con la mejor similitud de cada foto."""
    por_id: dict[int, Photo] = {}
    for foto in [*a, *b]:
        previa = por_id.get(foto.id)
        if previa is None or _sim(foto) > _sim(previa):
            por_id[foto.id] = foto
    return sorted(por_id.values(), key=_sim, reverse=True)[:limit]


def _es_dudosa(fotos: list[Photo], bandas: list[tuple[int, float]], threshold: float) -> bool:
    """¿La respuesta es corta porque la persona sale poco, o porque esta cara
    salió mal?

    La diferencia se ve al aflojar el umbral. Si sale poco de verdad, aflojar no
    trae casi nada (4 fotos → 5). Si la cara salió mal, aflojar la dispara
    (3 → 74), y a esa altura ya está matcheando a medio evento.
    """
    if len(fotos) > FACE_WEAK_MAX_PHOTOS:
        return False
    al_corte = len({pid for pid, d in bandas if 1 - float(d) >= threshold})
    al_flojo = len({pid for pid, d in bandas if 1 - float(d) >= FACE_WEAK_LOOSE})
    return al_corte > 0 and al_flojo >= al_corte * FACE_WEAK_FACTOR
