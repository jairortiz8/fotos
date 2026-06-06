"""Tests de accesibilidad estructural (Fase 7).

No reemplazan una auditoría con axe/Lighthouse en el navegador (eso lo corre
Jair), pero bloquean en CI las regresiones de accesibilidad más comunes:
landmark `main`, skip link, atributo `lang`, `alt` en imágenes, nombre
accesible en inputs y semántica de diálogo en el lightbox.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings as dj_settings
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.events.models import EventStatus
from apps.photos.models import BibSource
from tests.factories import ApprovedPhotoFactory, BibFactory, EventFactory

IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
H1_RE = re.compile(r"<h1\b", re.IGNORECASE)


@pytest.fixture(autouse=True)
def _locmem_cache(settings):  # type: ignore[no-untyped-def]
    """Cache aislado por test (rate limiting + search cache)."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.RATELIMIT_USE_CACHE = "default"
    cache.clear()
    yield
    cache.clear()


def _live_event_with_photo(bib: str = "1042"):  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE)
    photo = ApprovedPhotoFactory(event=event)
    BibFactory(photo=photo, number=bib, source=BibSource.OCR_PADDLE)
    return event, photo


@pytest.mark.django_db
def test_home_has_lang_skiplink_and_main(client: Client) -> None:
    html = client.get(reverse("core:index")).content.decode()
    assert re.search(r'<html[^>]*\blang="es"', html), "falta lang=es en <html>"
    assert 'class="rf-skip-link"' in html, "falta el skip link"
    assert 'href="#main-content"' in html, "el skip link no apunta a #main-content"
    assert 'id="main-content"' in html, "falta el landmark <main id=main-content>"


@pytest.mark.django_db
def test_skip_link_and_main_on_public_pages(client: Client) -> None:
    event, _ = _live_event_with_photo()
    urls = [
        reverse("core:index"),
        reverse("events:gallery", args=[event.slug]),
        reverse("privacy:delete_my_data"),
        reverse("privacy:policy"),
    ]
    for url in urls:
        html = client.get(url).content.decode()
        assert "rf-skip-link" in html, f"skip link faltante en {url}"
        assert 'id="main-content"' in html, f"<main> faltante en {url}"


@pytest.mark.django_db
def test_single_h1_on_key_pages(client: Client) -> None:
    """Una página accesible tiene exactamente un <h1>."""
    event, _ = _live_event_with_photo()
    for url in [reverse("core:index"), reverse("events:gallery", args=[event.slug])]:
        html = client.get(url).content.decode()
        n = len(H1_RE.findall(html))
        assert n == 1, f"se esperaba 1 <h1> en {url}, hay {n}"


@pytest.mark.django_db
def test_all_images_have_alt_in_search_results(client: Client) -> None:
    event, _ = _live_event_with_photo("1042")
    # En CI no hay R2 configurado → _presign devuelve "" y la galería muestra el
    # placeholder (sin <img>). Forzamos una URL para que el <img> se renderice y
    # así verificar de verdad que lleva alt (independiente de la config de R2).
    with patch("apps.photos.models.Photo._presign", return_value="https://x.test/t.webp"):
        html = client.get(
            reverse("events:gallery", args=[event.slug]), {"bib": "1042"}
        ).content.decode()
    imgs = IMG_RE.findall(html)
    assert imgs, "se esperaban imágenes en los resultados de búsqueda"
    missing = [t for t in imgs if "alt=" not in t]
    assert not missing, f"imágenes sin atributo alt: {missing}"


@pytest.mark.django_db
def test_bib_input_has_accessible_name(client: Client) -> None:
    event, _ = _live_event_with_photo()
    html = client.get(reverse("events:gallery", args=[event.slug])).content.decode()
    m = re.search(r"<input[^>]*name=\"bib\"[^>]*>", html)
    assert m is not None, "no se encontró el input de dorsal"
    assert "aria-label=" in m.group(0), "el input de dorsal no tiene nombre accesible"


@pytest.mark.django_db
def test_lightbox_has_dialog_semantics(client: Client) -> None:
    event, photo = _live_event_with_photo()
    html = client.get(reverse("events:lightbox", args=[event.slug, photo.id])).content.decode()
    assert 'role="dialog"' in html, "el lightbox no declara role=dialog"
    assert 'aria-modal="true"' in html, "el lightbox no declara aria-modal"
    assert "@keydown.escape" in html, "el lightbox no se cierra con Esc"


def test_pwa_icons_exist_on_disk() -> None:
    base = Path(dj_settings.BASE_DIR) / "static" / "img"
    for name in (
        "icon-192.png",
        "icon-512.png",
        "icon-maskable.png",
        "apple-touch-icon.png",
        "favicon-32.png",
    ):
        assert (base / name).is_file(), f"falta el icono PWA {name}"


@pytest.mark.django_db
def test_manifest_served_with_icons(client: Client) -> None:
    resp = client.get(reverse("core:manifest"))
    assert resp.status_code == 200
    assert "application/manifest+json" in resp["Content-Type"]
    data = json.loads(resp.content)
    assert data["name"], "el manifest debe traer name (de site_name)"
    assert len(data["icons"]) == 3
