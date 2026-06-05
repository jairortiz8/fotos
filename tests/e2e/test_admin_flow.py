"""E2E: el admin entra al dashboard con usuario y contraseña."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.factories import SuperUserFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_admin_can_log_in(live_server, page: Page) -> None:  # type: ignore[no-untyped-def]
    SuperUserFactory(username="admin-e2e")
    page.goto(f"{live_server.url}/dashboard/login/")
    page.fill('input[name="username"]', "admin-e2e")
    page.fill('input[name="password"]', "test-pass-1234")
    page.get_by_role("button", name="Iniciar sesión").click()
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page).to_have_url(f"{live_server.url}/dashboard/")
