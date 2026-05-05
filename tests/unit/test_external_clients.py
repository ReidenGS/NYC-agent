"""A9 — External-API clients (Socrata, RentCast, HUD User, Overpass) handle
pagination and translate HTTP failures to typed exceptions.

We mock httpx with httpx.MockTransport so no real network is touched.
"""
from __future__ import annotations

import importlib

import httpx
import pytest

from tests.conftest import add_service_to_path


@pytest.fixture(scope="module")
def clients():
    add_service_to_path("data-sync-service")
    return {
        "socrata": importlib.import_module("app.clients.socrata_client"),
        "rentcast": importlib.import_module("app.clients.rentcast_client"),
        "hud": importlib.import_module("app.clients.hud_user_client"),
        "overpass": importlib.import_module("app.clients.overpass_client"),
    }


def _make_handler(pages: list[list[dict]]):
    """Each call returns the next page from `pages`; subsequent calls return []."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = state["i"]
        state["i"] += 1
        body = pages[i] if i < len(pages) else []
        return httpx.Response(200, json=body)

    return handler


def _patch_httpx(monkeypatch, handler):
    """Force httpx.Client(...) to use a MockTransport."""
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


# --- Socrata pagination ------------------------------------------------------
def test_socrata_paginates_until_short_page(clients, monkeypatch):
    page1 = [{"id": str(i)} for i in range(5)]
    page2 = [{"id": "5"}, {"id": "6"}]  # short → stops
    _patch_httpx(monkeypatch, _make_handler([page1, page2]))

    monkeypatch.setattr(clients["socrata"].settings, "socrata_page_size", 5)
    monkeypatch.setattr(clients["socrata"].settings, "socrata_max_rows_per_job", 100)
    rows = list(clients["socrata"].fetch_all("dummy"))
    assert len(rows) == 7
    assert rows[0]["id"] == "0"
    assert rows[-1]["id"] == "6"


def test_socrata_respects_max_rows_cap(clients, monkeypatch):
    """Server respects $limit; client must shrink the second-page request to
    `max_rows - fetched`. Verify by echoing back exactly $limit rows."""
    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params.get("$limit", "1000"))
        offset = int(request.url.params.get("$offset", "0"))
        body = [{"id": str(offset + i)} for i in range(limit)]
        return httpx.Response(200, json=body)
    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(clients["socrata"].settings, "socrata_page_size", 10)
    monkeypatch.setattr(clients["socrata"].settings, "socrata_max_rows_per_job", 12)
    rows = list(clients["socrata"].fetch_all("dummy"))
    assert len(rows) == 12
    assert [r["id"] for r in rows[-3:]] == ["9", "10", "11"]


def test_socrata_retries_then_raises(clients, monkeypatch):
    """All retries fail → raises SocrataError, doesn't swallow silently."""
    def boom(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server fire")
    _patch_httpx(monkeypatch, boom)
    # Also stub time.sleep to keep the test fast.
    monkeypatch.setattr(clients["socrata"].time, "sleep", lambda *_: None)

    with pytest.raises(clients["socrata"].SocrataError):
        list(clients["socrata"].fetch_all("dummy"))


# --- HUD client --------------------------------------------------------------
def test_hud_client_returns_data_field_on_success(clients, monkeypatch):
    """fetch_fmr_for_county returns just the `data` value, not the wrapper."""
    fake = {"data": {"basicdata": {"One-Bedroom": 1500}}, "metadata": {}}
    _patch_httpx(monkeypatch, lambda r: httpx.Response(200, json=fake))
    monkeypatch.setattr(clients["hud"].settings, "hud_user_api_token", "fake-token")
    payload = clients["hud"].fetch_fmr_for_county("METRO12345", 2026)
    # The wrapper {"data": ...} is unwrapped; we get the inner dict directly.
    assert payload["basicdata"]["One-Bedroom"] == 1500


def test_hud_client_raises_on_auth_failure(clients, monkeypatch):
    _patch_httpx(monkeypatch, lambda r: httpx.Response(401, text="bad token"))
    monkeypatch.setattr(clients["hud"].settings, "hud_user_api_token", "tok")
    with pytest.raises(clients["hud"].HudError):
        clients["hud"].fetch_fmr_for_county("METRO1", 2026)


# --- RentCast budget gate ----------------------------------------------------
def test_rentcast_budget_blocks_when_run_cap_reached(clients):
    """Budget gate must refuse before any HTTP call once per-run cap hits."""
    budget = clients["rentcast"].RentCastBudget(max_per_run=2)
    assert budget.used == 0
    budget.check_and_increment()
    budget.check_and_increment()
    with pytest.raises(clients["rentcast"].RentCastQuotaExceeded):
        budget.check_and_increment()


# --- Overpass budget gate ----------------------------------------------------
def test_overpass_budget_quota_exceeded_raises(clients):
    """check_and_increment must raise once `used` hits `max_requests`. NOTE:
    OverpassBudget(max_requests=0) collapses to the default via `0 or default`,
    so we drive the gate explicitly with max_requests=1 + two increments."""
    budget = clients["overpass"].OverpassBudget(max_requests=1)
    budget.check_and_increment()  # used 0->1, OK
    with pytest.raises(clients["overpass"].OverpassQuotaExceeded):
        budget.check_and_increment()  # used==max → raise
