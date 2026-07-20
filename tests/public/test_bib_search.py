"""Tests de búsqueda por dorsal: filtrado, formato, cache, rate limiting."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.events.models import Event, EventStatus
from apps.photos.models import BibSource
from tests.factories import ApprovedPhotoFactory, BibFactory, EventFactory


@pytest.fixture(autouse=True)
def locmem_cache(settings):  # type: ignore[no-untyped-def]
    """Aísla el cache (rate limiting + search cache) con LocMem por test."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.RATELIMIT_USE_CACHE = "default"
    cache.clear()
    yield
    cache.clear()


def _event_with_bib(number: str = "1042") -> tuple[Event, object]:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number=number, source=BibSource.OCR_PADDLE)
    return event, photo


@pytest.mark.django_db
def test_search_returns_matching_photos(client: Client) -> None:
    event, photo = _event_with_bib("1042")
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "1042"})
    assert response.status_code == 200
    assert response.context["is_search_result"] is True
    assert photo in response.context["search_photos"]


@pytest.mark.django_db
def test_search_matches_leading_zero_bibs(client: Client) -> None:
    """El dorsal impreso con ceros ("099") se encuentra buscando "99" (sin cero)."""
    event, photo = _event_with_bib("099")
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "99"})
    assert response.status_code == 200
    assert response.context.get("is_search_result") is True
    assert photo in response.context["search_photos"]


@pytest.mark.django_db
def test_search_matches_unpadded_when_query_padded(client: Client) -> None:
    """Y al revés: dorsal "15" se encuentra buscando "015"."""
    event, photo = _event_with_bib("15")
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "015"})
    assert response.status_code == 200
    assert photo in response.context["search_photos"]


@pytest.mark.django_db
def test_search_does_not_overmatch_different_numbers(client: Client) -> None:
    """ "99" NO debe traer al dorsal "990" (número distinto, no es un cero a la izq)."""
    event, _photo = _event_with_bib("990")
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "99"})
    # Sin resultados → cae al template de "sin resultados" (no is_search_result).
    assert response.context.get("is_search_result") is None


@pytest.mark.django_db
def test_active_bib_chip_and_strip_clear_the_filter(client: Client) -> None:
    """Con un dorsal buscado, el chip resaltado y el pill del filtro linkean a
    QUITAR el filtro (galería sin ?bib), no a re-buscar el mismo dorsal."""
    event, _photo = _event_with_bib("1042")
    content = client.get(
        reverse("events:gallery", args=[event.slug]), {"bib": "1042"}
    ).content.decode()
    # El pill del filtro es un botón de "quitar" + hay un "Ver todas".
    assert "Quitar el filtro de dorsal y ver todas las fotos" in content
    assert "Ver todas" in content
    # El chip del dorsal buscado pasa a "quitar", ya no "ver todas las del 1042".
    assert "Quitar el filtro del dorsal 1042" in content
    assert "Ver todas las fotos del dorsal 1042" not in content


@pytest.mark.django_db
def test_search_normalizes_query_uppercase(client: Client) -> None:
    event, photo = _event_with_bib("A123")
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "a123"})
    assert photo in response.context["search_photos"]


@pytest.mark.django_db
def test_search_rejects_invalid_format(client: Client) -> None:
    event, _ = _event_with_bib()
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "12.34"})
    assert response.context.get("error") == "invalid_format"


@pytest.mark.django_db
def test_search_empty_results_shows_similar_bibs(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="9999", source=BibSource.OCR_PADDLE)
    # 8999 no existe pero 9999 es variante OCR (8→9)
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "8999"})
    assert response.status_code == 200
    assert "9999" in response.context["similar_bibs"]


@pytest.mark.django_db
def test_search_increments_event_search_count(client: Client) -> None:
    event, _ = _event_with_bib("1042")
    assert event.search_count == 0
    client.get(reverse("events:gallery", args=[event.slug]), {"bib": "1042"})
    event.refresh_from_db()
    assert event.search_count == 1


@pytest.mark.django_db
def test_search_cached(client: Client) -> None:
    event, _ = _event_with_bib("1042")
    client.get(reverse("events:gallery", args=[event.slug]), {"bib": "1042"})
    cache_key = f"search:bib:{event.id}:1042"
    assert cache.get(cache_key) is not None


@pytest.mark.django_db
def test_search_excludes_rejected_bibs(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number="1042", source=BibSource.OCR_PADDLE, rejected=True)
    response = client.get(reverse("events:gallery", args=[event.slug]), {"bib": "1042"})
    # bib rechazado → no aparece en resultados (empty state)
    assert b"No encontramos" in response.content


@pytest.mark.django_db
def test_bib_specific_rate_limit_10_per_day(client: Client) -> None:
    """La 11ª búsqueda del MISMO dorsal por la misma IP da 429."""
    event, _ = _event_with_bib("1042")
    url = reverse("events:gallery", args=[event.slug])
    # 10 OK
    for _ in range(10):
        r = client.get(url, {"bib": "1042"}, REMOTE_ADDR="9.9.9.9")
        assert r.status_code == 200
    # 11ª → 429
    r = client.get(url, {"bib": "1042"}, REMOTE_ADDR="9.9.9.9")
    assert r.status_code == 429


@pytest.mark.django_db
def test_general_rate_limit_blocks_after_60(client: Client) -> None:
    """Búsquedas de dorsales DISTINTOS comparten el límite general 60/h por IP."""
    event = EventFactory(status=EventStatus.LIVE)
    url = reverse("events:gallery", args=[event.slug])
    # 60 dorsales distintos (cada uno cuenta para el límite general).
    last_status = 200
    for i in range(62):
        r = client.get(url, {"bib": str(1000 + i)}, REMOTE_ADDR="8.8.8.8")
        last_status = r.status_code
        if last_status == 429:
            break
    assert last_status == 429
