"""Shared MOTIS stub.

The planner routes through Transitous now, so any test that expects rail must
stub MOTIS rather than the DB adapter. Autouse and network-free: a test that
reaches the real api.transitous.org is a bug, not a slow test.
"""

from datetime import datetime, timedelta

import pytest

from app import cache as cache_mod

# pair -> (fast minutes, changes, regional minutes)
ROUTES = {
    frozenset({"Dortmund", "München"}): (305, 1, 620),
    frozenset({"Berlin", "Hamburg"}): (110, 0, 235),
    frozenset({"Köln", "Berlin"}): (260, 0, 560),
    frozenset({"Dortmund", "Essen"}): (33, 0, 38),
    frozenset({"München", "Hamburg"}): (345, 0, 700),
    frozenset({"Frankfurt am Main", "Stuttgart"}): (78, 0, 152),
    frozenset({"Berlin", "München"}): (240, 0, 545),
    frozenset({"Dortmund", "Berlin"}): (245, 1, 500),
    frozenset({"Dortmund", "Frankfurt am Main"}): (135, 0, 300),
}
CURRENT: dict = {"pair": None}


def _motis_itinerary(when: datetime, minutes: int, changes: int, *, regional: bool):
    mode = "REGIONAL_RAIL" if regional else "HIGHSPEED_RAIL"
    legs = [{
        "mode": "WALK", "startTime": when.isoformat(),
        "endTime": (when + timedelta(minutes=9)).isoformat(),
        "distance": 700, "to": {"name": "Hbf"}, "from": {"name": "start"},
    }]
    cursor = when + timedelta(minutes=20)
    ride = max(1, minutes // (changes + 1))
    for i in range(changes + 1):
        legs.append({
            "mode": mode, "routeShortName": f"ICE {600+i}",
            "startTime": cursor.isoformat(),
            "endTime": (cursor + timedelta(minutes=ride)).isoformat(),
            "distance": ride * 2000,
            "to": {"name": f"stop{i+1}"}, "from": {"name": f"stop{i}"},
        })
        cursor += timedelta(minutes=ride + 12)
    total = int((cursor - when).total_seconds() // 60)
    return {
        "startTime": when.isoformat(),
        "endTime": (when + timedelta(minutes=total)).isoformat(),
        "duration": total * 60, "transfers": changes, "id": "stub", "legs": legs,
    }


@pytest.fixture(autouse=True)
def stub_motis(monkeypatch):
    cache_mod.cache._local.clear()

    async def fake_get(path: str, params: dict):
        if path == "/api/v1/geocode":
            return [{"id": "stub", "name": params.get("text"), "type": "STOP",
                     "lat": 51.51, "lon": 7.46}]
        when = datetime.fromisoformat(params["time"])
        fast, changes, regional_min = ROUTES.get(CURRENT["pair"], (180, 0, 360))
        if params.get("transitModes"):
            return {"itineraries": [
                _motis_itinerary(when, regional_min, changes + 2, regional=True)]}
        return {"itineraries": [
            _motis_itinerary(when, fast, changes, regional=False)]}

    monkeypatch.setattr("app.providers.motis._get", fake_get)
    yield


@pytest.fixture
def set_route():
    def _set(a: str, b: str):
        CURRENT["pair"] = frozenset({a, b})
    return _set
