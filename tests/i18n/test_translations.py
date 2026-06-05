"""Tests de internacionalización (Fase 7).

El idioma fuente de RunFoto es español (vos). Por eso:
- ``locale/es`` está COMPLETO (msgstr == msgid; lo llena ``msgen``).
- ``locale/en`` es un PLACEHOLDER vacío (todas las traducciones en blanco), listo
  para que alguien lo complete en el futuro sin tocar templates.

Estos tests leen los catálogos ``.mo`` ya compilados (commiteados), así que no
dependen del binario ``gettext`` al correr — andan igual en CI.
"""

from __future__ import annotations

import gettext as gettext_module
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from django.utils import translation

LOCALE_DIR = Path(settings.BASE_DIR) / "locale"


def test_locale_catalogs_compiled() -> None:
    """Los .mo de es y en existen (sin ellos, prod no traduce)."""
    assert (LOCALE_DIR / "es/LC_MESSAGES/django.mo").exists()
    assert (LOCALE_DIR / "en/LC_MESSAGES/django.mo").exists()


def test_es_catalog_is_populated() -> None:
    """es es el idioma activo y fuente → el catálogo tiene que estar lleno."""
    cat = gettext_module.translation("django", str(LOCALE_DIR), ["es"])
    # 569 mensajes al cierre de Fase 7; pedimos un piso amplio para no ser frágil.
    assert len(cat._catalog) > 200  # type: ignore[attr-defined]


def test_en_catalog_is_placeholder() -> None:
    """en queda vacío a propósito (placeholder): sólo la cabecera."""
    cat = gettext_module.translation("django", str(LOCALE_DIR), ["en"])
    # Catálogo vacío → sólo la clave '' (header). <= 1 entrada.
    assert len(cat._catalog) <= 1  # type: ignore[attr-defined]


def test_known_string_is_translatable_in_es() -> None:
    """Una string conocida envuelta en {% trans %} resuelve en español."""
    with translation.override("es"):
        assert translation.gettext("Borrar mis datos") == "Borrar mis datos"


def test_blocktrans_plural_forms_present() -> None:
    """El catálogo es incluye formas plurales (msgid_plural → tupla en _catalog)."""
    cat = gettext_module.translation("django", str(LOCALE_DIR), ["es"])
    plural_keys = [k for k in cat._catalog if isinstance(k, tuple)]  # type: ignore[attr-defined]
    assert plural_keys, "Se esperaban entradas con plural (blocktrans count)."


@pytest.mark.django_db
def test_changing_language_via_set_language_works(client: Client) -> None:
    """El endpoint set_language (django.conf.urls.i18n) cambia el idioma activo."""
    resp = client.post(
        reverse("set_language"),
        {"language": "es", "next": "/"},
        HTTP_REFERER="/",
    )
    # set_language redirige (302) tras fijar la cookie de idioma.
    assert resp.status_code == 302
    assert settings.LANGUAGE_COOKIE_NAME in resp.cookies


@pytest.mark.django_db
def test_public_page_renders_in_es(client: Client) -> None:
    """La home renderiza en español (idioma por defecto), sin romper i18n."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp["Content-Language"].startswith("es")
