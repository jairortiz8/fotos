"""El Instagram del fotógrafo: lo carga él desde su portal y sale en el álbum.

Lo que importa acá no es sólo que se guarde, sino QUÉ se guarda: nunca una URL
suelta. Esto se renderiza como link en una página pública, así que si
aceptáramos `https://loquesea.com` el álbum pasaría a ser un trampolín a
cualquier lado. Guardamos sólo el usuario y armamos nosotros la URL.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.events.models import EventStatus
from apps.photographers.models import PhotographerLink, normalize_instagram
from tests.factories import ApprovedPhotoFactory, EventFactory


# ---------------------------------------------------------------------------
# Normalización: las tres formas en que alguien lo va a pegar
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("foto", "foto"),
        ("@foto", "foto"),
        ("  @foto.oficial  ", "foto.oficial"),
        ("https://instagram.com/foto", "foto"),
        ("https://www.instagram.com/foto/", "foto"),
        ("https://www.instagram.com/foto/?hl=es", "foto"),
        ("HTTPS://Instagram.com/Foto", "Foto"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normaliza_a_usuario_pelado(entrada: str, esperado: str) -> None:
    assert normalize_instagram(entrada) == esperado


@pytest.mark.parametrize(
    "entrada",
    [
        "https://loquesea.com/malo",  # otro sitio: el álbum no es un trampolín
        "javascript:alert(1)",
        "foto con espacios",
        "a" * 31,  # Instagram corta en 30
        "<script>",
        "foto/../otro",
    ],
)
def test_rechaza_lo_que_no_es_un_usuario_de_instagram(entrada: str) -> None:
    with pytest.raises(ValueError):
        normalize_instagram(entrada)


@pytest.mark.django_db
def test_la_url_la_armamos_nosotros() -> None:
    event = EventFactory()
    link, _ = PhotographerLink.generate_token_and_create(
        event, name="Foto", instagram="@foto.oficial"
    )
    assert link.instagram == "foto.oficial"
    assert link.instagram_url() == "https://instagram.com/foto.oficial"
    assert link.instagram_handle() == "@foto.oficial"


@pytest.mark.django_db
def test_sin_instagram_no_hay_link_ni_arroba() -> None:
    event = EventFactory()
    link, _ = PhotographerLink.generate_token_and_create(event, name="Foto")
    assert link.instagram == ""
    assert link.instagram_url() == ""
    assert link.instagram_handle() == ""


# ---------------------------------------------------------------------------
# El portal: el fotógrafo lo carga solo, autenticado por el token de la URL
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_el_fotografo_guarda_su_instagram_desde_el_portal(client: Client) -> None:
    event = EventFactory()
    link, token = PhotographerLink.generate_token_and_create(event, name="Foto")

    r = client.post(
        reverse("photographer:social", args=[token]),
        {"instagram": "https://www.instagram.com/foto.sv/?hl=es"},
    )
    assert r.status_code == 200
    assert r.json() == {
        "instagram": "foto.sv",
        "instagram_url": "https://instagram.com/foto.sv",
    }
    link.refresh_from_db()
    assert link.instagram == "foto.sv"


@pytest.mark.django_db
def test_puede_borrarlo_mandando_vacio(client: Client) -> None:
    event = EventFactory()
    link, token = PhotographerLink.generate_token_and_create(event, name="Foto", instagram="foto")

    r = client.post(reverse("photographer:social", args=[token]), {"instagram": ""})
    assert r.status_code == 200
    link.refresh_from_db()
    assert link.instagram == ""


@pytest.mark.django_db
def test_un_usuario_invalido_devuelve_400_y_no_pisa_lo_guardado(client: Client) -> None:
    event = EventFactory()
    link, token = PhotographerLink.generate_token_and_create(event, name="Foto", instagram="foto")

    r = client.post(
        reverse("photographer:social", args=[token]),
        {"instagram": "https://sitio-raro.com/x"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_instagram"
    link.refresh_from_db()
    assert link.instagram == "foto", "un valor inválido no puede borrar el que ya estaba"


@pytest.mark.django_db
def test_con_un_token_que_no_existe_no_se_puede_guardar(client: Client) -> None:
    r = client.post(reverse("photographer:social", args=["token-inventado"]), {"instagram": "x"})
    assert r.status_code == 410


@pytest.mark.django_db
def test_con_el_link_revocado_tampoco(client: Client) -> None:
    event = EventFactory()
    link, token = PhotographerLink.generate_token_and_create(event, name="Foto")
    link.revoke("prueba")

    r = client.post(reverse("photographer:social", args=[token]), {"instagram": "foto"})
    assert r.status_code == 410
    link.refresh_from_db()
    assert link.instagram == ""


# ---------------------------------------------------------------------------
# El álbum público: que efectivamente se vea
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_sale_en_la_tarjeta_de_la_carpeta(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    link, _ = PhotographerLink.generate_token_and_create(event, name="Foto", instagram="foto.sv")
    ApprovedPhotoFactory(event=event, photographer_link=link)

    html = client.get(
        reverse("events:gallery", args=[event.slug]), {"vista": "fotografos"}
    ).content.decode()
    assert "@foto.sv" in html


@pytest.mark.django_db
def test_al_entrar_a_la_carpeta_el_instagram_es_clickeable(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    link, _ = PhotographerLink.generate_token_and_create(event, name="Foto", instagram="foto.sv")
    ApprovedPhotoFactory(event=event, photographer_link=link)

    html = client.get(
        reverse("events:gallery", args=[event.slug]), {"fotografo": link.id}
    ).content.decode()
    assert 'href="https://instagram.com/foto.sv"' in html
    assert 'rel="noopener noreferrer nofollow"' in html


@pytest.mark.django_db
def test_sin_instagram_la_carpeta_no_muestra_una_arroba_vacia(client: Client) -> None:
    event = EventFactory(status=EventStatus.LIVE)
    link, _ = PhotographerLink.generate_token_and_create(event, name="Foto")
    ApprovedPhotoFactory(event=event, photographer_link=link)

    html = client.get(
        reverse("events:gallery", args=[event.slug]), {"fotografo": link.id}
    ).content.decode()
    # Lo que no queremos es un link a un perfil vacío ni un "@" colgado.
    assert 'href="https://instagram.com/"' not in html
    assert "@</span>" not in html
