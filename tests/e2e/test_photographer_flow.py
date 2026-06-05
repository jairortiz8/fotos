"""E2E: portal del fotógrafo — un token vencido devuelve 410 con mensaje claro."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from apps.photographers.models import _hash_token
from tests.factories import ExpiredPhotographerLinkFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_expired_token_shows_invalid_link_message(live_server, page: Page) -> None:  # type: ignore[no-untyped-def]
    raw = "token-vencido-e2e"
    ExpiredPhotographerLinkFactory(token_hash=_hash_token(raw))
    resp = page.goto(f"{live_server.url}/u/{raw}/")
    assert resp is not None and resp.status == 410
    expect(page.get_by_text("ya no es válido")).to_be_visible()
