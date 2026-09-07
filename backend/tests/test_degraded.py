"""The Dortmund-Frankfurt bug: rail down, coach shown alone, no warning.

A provider being unreachable and a provider having no service are different
facts and must not produce the same output.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import cache as cache_mod
from app.main import app
from app.providers.base import UpstreamUnavailable

BERLIN = timezone(timedelta(hours=2))
DEPART = (datetime.now(BERLIN) + timedelta(days=21)).replace(
    hour=8, minute=0, second=0, microsecond=0)


@pytest.fixture
def rail_down(monkeypatch):
    """Transitous unreachable. Overrides the autouse stub in conftest."""
    cache_mod.cache._local.clear()

    async def boom(path, params):
        raise UpstreamUnavailable("Transitous unreachable after 3 attempts (HTTP 503)")

    monkeypatch.setattr("app.providers.motis._get", boom)
    monkeypatch.setattr("app.providers.db_rail.db_get", boom)
    with TestClient(app) as c:
        yield c


def test_rail_outage_is_reported_not_hidden(rail_down):
    body = rail_down.get("/api/plan", params={
        "origin": "Dortmund", "destination": "Frankfurt am Main",
        "depart": DEPART.isoformat()}).json()
    assert body["degraded"] is True
    assert any("503" in w or "unreachable" in w.lower() for w in body["warnings"])


def test_a_lone_coach_is_flagged_as_not_a_fair_comparison(rail_down):
    body = rail_down.get("/api/plan", params={
        "origin": "Dortmund", "destination": "Frankfurt am Main",
        "depart": DEPART.isoformat()}).json()
    modes = {o["mode"] for o in body["options"]}
    assert not any(m.startswith("rail") for m in modes)
    assert "NOT a fair comparison" in body["warnings"][0]


def test_healthy_rail_is_not_flagged_degraded(set_route):
    """The conftest stub supplies a 2h15 ICE for this pair."""
    set_route("Dortmund", "Frankfurt am Main")
    with TestClient(app) as c:
        body = c.get("/api/plan", params={
            "origin": "Dortmund", "destination": "Frankfurt am Main",
            "depart": DEPART.isoformat()}).json()
    assert body["degraded"] is False
    rail = next(o for o in body["options"] if o["mode"] == "rail")
    # 2h15 ICE must beat the 4h20 modelled coach it was losing to.
    assert rail["door_to_door_minutes"] < 200
    assert body["options"][0]["mode"] == "rail"


def test_location_search_falls_back_to_catalogue_when_upstream_is_down(monkeypatch):
    """The typeahead must keep working during an outage, not go blank."""
    cache_mod.cache._local.clear()

    async def boom(path, params):
        raise UpstreamUnavailable("HTTP 503")

    monkeypatch.setattr("app.providers.motis._get", boom)
    monkeypatch.setattr("app.providers.db_rail.db_get", boom)
    with TestClient(app) as c:
        hits = c.get("/api/locations", params={"q": "Dort"}).json()
    assert any(h["name"] == "Dortmund" for h in hits)


def test_location_search_prefers_live_geocoder_results():
    """conftest's stub geocoder answers; the catalogue is never consulted."""
    with TestClient(app) as c:
        hits = c.get("/api/locations", params={"q": "Dortmund Hbf"}).json()
    assert hits[0]["name"] == "Dortmund Hbf"
    assert hits[0]["kind"] == "stop"


def test_modelled_flights_are_hidden_by_default(monkeypatch):
    """A stranger reads EUR 135.71 as a price, badge or no badge."""
    from app.config import settings
    assert settings.enable_air is False


def test_admin_page_is_served(rail_down):
    assert rail_down.get("/admin").status_code == 200
