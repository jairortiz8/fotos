"""La cáscara pública: que ninguna página quede sin salida.

`base.html` no trae header ni footer (la usan también el dashboard, el portal
del fotógrafo y el reviewer, que no los quieren), así que cada página se dibujaba
el suyo a mano. Resultado: las páginas legales no tenían NINGUNO — el que entraba
a Preguntas frecuentes desde el footer no tenía cómo volver más que con el botón
atrás del navegador.

Ahora todo eso vive en `public/base_public.html`. Estos tests son la red que
impide que vuelva a pasar: si alguien agrega una página pública extendiendo
`base.html` a secas, el test la caza.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

# Marcas que sólo aparecen si el partial se renderizó.
MARCA_HEADER = 'class="rf-wordmark"'
MARCA_FOOTER = "Sin cuentas. Sin costo. Solo tus fotos."

# Páginas públicas que se sirven sin datos previos.
PAGINAS_SUELTAS = [
    "core:faq",
    "core:terminos",
    "core:cookies",
    "core:contacto",
    "privacy:policy",
]


@pytest.mark.django_db
@pytest.mark.parametrize("nombre", PAGINAS_SUELTAS)
def test_toda_pagina_publica_tiene_header_y_footer(client: Client, nombre: str) -> None:
    r = client.get(reverse(nombre))
    assert r.status_code == 200
    html = r.content.decode()
    assert MARCA_HEADER in html, f"{nombre} quedó sin header: no hay cómo volver"
    assert MARCA_FOOTER in html, f"{nombre} quedó sin footer: es un callejón sin salida"


@pytest.mark.django_db
@pytest.mark.parametrize("nombre", PAGINAS_SUELTAS)
def test_el_footer_lleva_a_las_otras_paginas(client: Client, nombre: str) -> None:
    """Desde cualquiera de ellas se llega a las demás y a la home."""
    html = client.get(reverse(nombre)).content.decode()
    for destino in ("core:index", "core:faq", "privacy:policy", "core:terminos"):
        assert f'href="{reverse(destino)}"' in html, f"{nombre} no linkea a {destino}"


@pytest.mark.django_db
def test_la_home_no_duplica_el_footer(client: Client) -> None:
    """El footer vivía dentro de home.html y era la única copia del sitio. Al
    sacarlo al partial, la home tiene que seguir teniendo UNO — no cero, ni dos."""
    html = client.get(reverse("core:index")).content.decode()
    assert html.count("<footer") == 1
    assert MARCA_FOOTER in html


@pytest.mark.django_db
def test_el_lightbox_no_hereda_la_cascara(client: Client) -> None:
    """El lightbox es una capa a pantalla completa: un header y un footer arriba
    de la foto lo romperían. Tiene que seguir extendiendo `base.html` pelada."""
    from apps.events.models import EventStatus
    from tests.factories import ApprovedPhotoFactory, EventFactory

    event = EventFactory(status=EventStatus.LIVE)
    foto = ApprovedPhotoFactory(event=event)
    html = client.get(reverse("events:lightbox", args=[event.slug, foto.id])).content.decode()
    assert "<footer" not in html
    assert MARCA_FOOTER not in html
