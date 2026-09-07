"""End-to-end test with only the outermost HTTP call stubbed.

Everything below `db_get` is the real code path: catalogue lookup, station
resolution, caching, the DB parser, the air and coach providers, fan-out,
scoring and JSON serialisation.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import cache as cache_mod
from app.main import app
from app.providers import base as base_mod

BERLIN = timezone(timedelta(hours=2))
DEPART = (datetime.now(BERLIN) + timedelta(days=21)).replace(hour=8, minute=0, second=0, microsecond=0)


def _stub_journey(dep: datetime):
    return {
        "journeys": [
            {
                "legs": [
                    {
                        "origin": {"latitude": 51.51, "longitude": 7.46, "address": "start"},
                        "destination": {"type": "stop", "id": "8000080", "name": "Dortmund Hbf",
                                        "location": {"latitude": 51.5177, "longitude": 7.4592}},
                        "departure": dep.isoformat(),
                        "arrival": (dep + timedelta(minutes=11)).isoformat(),
                        "walking": True, "distance": 850,
                    },
                    {
                        "origin": {"type": "stop", "id": "8000080", "name": "Dortmund Hbf",
                                   "location": {"latitude": 51.5177, "longitude": 7.4592}},
                        "destination": {"type": "stop", "id": "8000261", "name": "München Hbf",
                                        "location": {"latitude": 48.1402, "longitude": 11.5586}},
                        "departure": (dep + timedelta(minutes=25)).isoformat(),
                        "arrival": (dep + timedelta(minutes=25 + 305)).isoformat(),
                        "line": {"name": "ICE 619", "product": "nationalExpress", "mode": "train"},
                    },
                ],
                "price": {"amount": 89.9, "currency": "EUR"},
            }
        ]
    }


@pytest.fixture(autouse=True)
def enable_air(monkeypatch):
    from app import planner
    from app.providers.air import AirProvider
    monkeypatch.setattr(planner, "PROVIDERS", [*planner.PROVIDERS, AirProvider()])


@pytest.fixture(autouse=True)
def _route(request):
    from tests.conftest import CURRENT
    CURRENT["pair"] = frozenset({"Dortmund", "München"})


@pytest.fixture(autouse=True)
def stub_db(monkeypatch):
    cache_mod.cache._local.clear()

    async def fake_db_get(path: str, params: dict):
        if path == "/locations":
            return [{"id": "8000080", "name": params.get("query")}]
        dep_raw = params.get("departure")
        dep = datetime.fromisoformat(dep_raw) if dep_raw else DEPART
        return _stub_journey(dep)

    monkeypatch.setattr(base_mod, "db_get", fake_db_get)
    monkeypatch.setattr("app.providers.db_rail.db_get", fake_db_get)
    yield


def test_plan_returns_multiple_modes_ranked():
    with TestClient(app) as client:
        resp = client.get("/api/plan", params={
            "origin": "Dortmund", "destination": "München",
            "depart": DEPART.isoformat(), "preset": "balanced",
        })
    assert resp.status_code == 200
    body = resp.json()
    modes = {o["mode"] for o in body["options"]}
    assert "rail" in modes
    assert "air" in modes and "coach" in modes
    assert body["options"][0]["match"] == 100


def test_every_option_reports_a_door_to_door_envelope_longer_than_its_ride():
    with TestClient(app) as client:
        body = client.get("/api/plan", params={
            "origin": "Dortmund", "destination": "Berlin", "depart": DEPART.isoformat(),
        }).json()
    for opt in body["options"]:
        ride = sum(l["minutes"] for l in opt["legs"] if l["kind"] == "ride")
        assert opt["door_to_door_minutes"] > ride, opt["mode"]


def test_flight_option_carries_a_real_access_leg_not_a_guess():
    with TestClient(app) as client:
        body = client.get("/api/plan", params={
            "origin": "Dortmund", "destination": "München", "depart": DEPART.isoformat(),
            "preset": "fastest",
        }).json()
    air = next(o for o in body["options"] if o["mode"] == "air")
    access = next(l for l in air["legs"] if l["kind"] == "access")
    assert "estimated" not in access["label"]
    assert access["minutes"] > 0


def test_no_flight_is_offered_on_a_route_with_no_service():
    with TestClient(app) as client:
        body = client.get("/api/plan", params={
            "origin": "Dortmund", "destination": "Essen", "depart": DEPART.isoformat(),
        }).json()
    assert not any(o["mode"] == "air" for o in body["options"])


def test_deutschlandticket_surfaces_a_zero_fare_option():
    with TestClient(app) as client:
        body = client.get("/api/plan", params={
            "origin": "Dortmund", "destination": "Berlin", "depart": DEPART.isoformat(),
            "deutschlandticket": "true", "preset": "cheapest",
        }).json()
    assert any(o["total_cents"] == 0 for o in body["options"])


def test_unknown_place_is_a_clean_404(monkeypatch):
    """With the geocoder returning nothing, an unresolvable name must 404
    rather than silently plan from the wrong coordinates."""
    async def nothing(path, params):
        return [] if path == "/api/v1/geocode" else {"itineraries": []}

    monkeypatch.setattr("app.providers.motis._get", nothing)
    with TestClient(app) as client:
        assert client.get("/api/plan", params={
            "origin": "Atlantis", "destination": "Berlin"}).status_code == 404


def test_bad_preset_is_rejected():
    with TestClient(app) as client:
        assert client.get("/api/plan", params={
            "origin": "Berlin", "destination": "München", "preset": "vibes"}).status_code == 400
