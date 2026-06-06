"""E2E: flujo del corredor — buscar por dorsal, empty state, evento archivado."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from apps.events.models import EventStatus
from apps.photos.models import BibSource
from tests.factories import (
    ApprovedPhotoFactory,
    ArchivedEventFactory,
    BibFactory,
    EventFactory,
)

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _seed_event_with_bib(slug: str, bib: str, n: int = 3):  # type: ignore[no-untyped-def]
    event = EventFactory(status=EventStatus.LIVE, slug=slug, name="Maratón E2E 2026")
    for _ in range(n):
        photo = ApprovedPhotoFactory(event=event)
        BibFactory(photo=photo, number=bib, source=BibSource.OCR_PADDLE)
    return event


def test_runner_searches_by_bib_and_sees_results(live_server, page: Page) -> None:  # type: ignore[no-untyped-def]
    event = _seed_event_with_bib("maraton-e2e-1", "1042", n=3)
    page.goto(f"{live_server.url}/eventos/{event.slug}/")
    expect(page.get_by_role("heading", name="Maratón E2E 2026")).to_be_visible()
    page.fill('input[name="bib"]', "1042")
    page.press('input[name="bib"]', "Enter")
    # Cada resultado enlaza al lightbox /foto/<id>/. Chequeamos que EXISTAN
    # (count), no su visibilidad pixel-perfect: el job de E2E no compila el CSS
    # de Tailwind, así que las cards (que toman alto del aspect-ratio) colapsan.
    page.wait_for_selector('a[href*="/foto/"]', state="attached", timeout=10000)
    assert page.locator('a[href*="/foto/"]').count() >= 1


def test_runner_unknown_bib_shows_empty_state(live_server, page: Page) -> None:  # type: ignore[no-untyped-def]
    event = _seed_event_with_bib("maraton-e2e-2", "1042", n=2)
    page.goto(f"{live_server.url}/eventos/{event.slug}/?bib=99999")
    expect(page.get_by_text("No encontramos fotos")).to_be_visible()
    assert page.locator('a[href*="/foto/"]').count() == 0


def test_archived_event_blocks_public_gallery(live_server, page: Page) -> None:  # type: ignore[no-untyped-def]
    event = ArchivedEventFactory(slug="archivado-e2e")
    page.goto(f"{live_server.url}/eventos/{event.slug}/")
    # La galería pública de un evento archivado queda bloqueada: sin buscador.
    assert page.locator('input[name="bib"]').count() == 0
    expect(page.get_by_text("no está disponible")).to_be_visible()
