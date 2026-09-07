"""Scenario coverage across real German city pairs.

Each case asserts something that must hold for that *shape* of route, not a
frozen number. Fares and timetables move; the properties do not. If a change
to the model breaks one of these, the model is wrong.

The DB layer is stubbed with realistic ICE timings so the matrix is
reproducible offline and in CI. Timings below are the published fast-service
durations for each pair, rounded.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import cache as cache_mod
from app.main import app
from app.providers import base as base_mod

BERLIN = timezone(timedelta(hours=2))
DEPART = (datetime.now(BERLIN) + timedelta(days=21)).replace(
    hour=8, minute=0, second=0, microsecond=0
)

# pair -> (fast rail minutes, typical advance fare €, changes)
RAIL_TIMES = {
    ("Dortmund", "München"): (305, 89.90, 1),
    ("Berlin", "Hamburg"): (110, 49.90, 0),
    ("Köln", "Berlin"): (260, 79.90, 0),
    ("Dortmund", "Essen"): (33, 9.60, 0),
    ("München", "Hamburg"): (345, 109.90, 0),
    ("Frankfurt am Main", "Stuttgart"): (78, 39.90, 0),
    ("Berlin", "München"): (240, 99.90, 0),
    ("Dortmund", "Berlin"): (245, 69.90, 1),
}
_ACTIVE: dict = {}


def _journey(dep: datetime, minutes: int, fare: float, changes: int):
    legs = [{
        "origin": {"latitude": 51.5, "longitude": 7.4, "address": "start"},
        "destination": {"type": "stop", "name": "Hbf",
                        "location": {"latitude": 51.51, "longitude": 7.45}},
        "departure": dep.isoformat(),
        "arrival": (dep + timedelta(minutes=9)).isoformat(),
        "walking": True, "distance": 700,
    }]
    cursor = dep + timedelta(minutes=20)
    ride = minutes // (changes + 1)
    for i in range(changes + 1):
        legs.append({
            "origin": {"type": "stop", "name": f"stop{i}",
                       "location": {"latitude": 51.5 + i, "longitude": 7.4 + i}},
            "destination": {"type": "stop", "name": f"stop{i+1}",
                            "location": {"latitude": 51.5 + i + 1, "longitude": 7.4 + i + 1}},
            "departure": cursor.isoformat(),
            "arrival": (cursor + timedelta(minutes=ride)).isoformat(),
            "line": {"name": f"ICE {600+i}", "product": "nationalExpress", "mode": "train"},
        })
        cursor += timedelta(minutes=ride + 12)
    return {"legs": legs, "price": {"amount": fare, "currency": "EUR"}}


@pytest.fixture(autouse=True)
def stub_db(monkeypatch):
    cache_mod.cache._local.clear()

    async def fake_db_get(path: str, params: dict):
        if path == "/locations":
            return [{"id": "8000080", "name": params.get("query")}]
        dep = datetime.fromisoformat(params["departure"])
        minutes, fare, changes = _ACTIVE.get("times", (180, 59.90, 0))
        if params.get("national") == "false":     # Deutschlandticket routing
            minutes, changes = int(minutes * 1.8), changes + 2
        if params.get("results") == 1:            # an airport access leg
            minutes, fare, changes = 48, 12.40, 0
        return {"journeys": [_journey(dep, minutes, fare, changes)]}

    monkeypatch.setattr(base_mod, "db_get", fake_db_get)
    monkeypatch.setattr("app.providers.db_rail.db_get", fake_db_get)
    yield


@pytest.fixture
def with_flights(monkeypatch):
    """Flights are off by default now. Tests that assert on them must opt in,
    which is the point: the default has to be the safe one.

    Settings is a frozen dataclass, so the provider list is swapped directly
    rather than mutating config.
    """
    from app import planner
    from app.providers.air import AirProvider

    monkeypatch.setattr(planner, "PROVIDERS", [*planner.PROVIDERS, AirProvider()])


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def search(client, origin, destination, **kw):
    from tests.conftest import CURRENT
    CURRENT["pair"] = frozenset({origin, destination})
    params = {"origin": origin, "destination": destination,
              "depart": DEPART.isoformat(), **kw}
    resp = client.get("/api/plan", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def mode(body, name):
    return next((o for o in body["options"] if o["mode"] == name), None)


# ---------------------------------------------------------------- long haul

def test_dortmund_munich_flight_barely_beats_the_train_and_costs_far_more(client, with_flights):
    """The headline case. If this ever inverts, check the airport access leg."""
    body = search(client, "Dortmund", "München", preset="balanced")
    rail, air = mode(body, "rail"), mode(body, "air")
    assert air and rail
    assert air["door_to_door_minutes"] > rail["door_to_door_minutes"] - 90
    assert air["total_cents"] > rail["total_cents"]
    assert body["options"][0]["mode"] == "rail"


def test_munich_hamburg_is_where_flying_starts_to_make_sense(client, with_flights):
    """Germany's longest domestic pair. Air should at least be competitive."""
    body = search(client, "München", "Hamburg", preset="fastest")
    air = mode(body, "air")
    assert air is not None
    assert air["door_to_door_minutes"] < mode(body, "rail")["door_to_door_minutes"]


# --------------------------------------------------------------- short haul

def test_berlin_hamburg_offers_no_flight_because_none_is_scheduled(client):
    body = search(client, "Berlin", "Hamburg")
    assert mode(body, "air") is None
    assert body["options"][0]["mode"] in {"rail", "rail_regional"}


def test_dortmund_essen_has_neither_flight_nor_coach(client):
    """Under 40 km. Anything but a train here would be a modelling bug."""
    body = search(client, "Dortmund", "Essen")
    assert mode(body, "air") is None
    assert mode(body, "coach") is None
    assert body["options"]


# ------------------------------------------------------------------ presets

@pytest.mark.parametrize("preset", ["cheapest", "fastest", "balanced", "laptop", "low_carbon"])
def test_every_preset_returns_a_coherent_ranking(client, preset):
    body = search(client, "Köln", "Berlin", preset=preset)
    assert body["options"], preset
    assert body["options"][0]["match"] == 100
    scores = [o["generalized_cents"] for o in body["options"]]
    assert scores == sorted(scores), f"{preset} returned an unsorted ranking"


def test_cheapest_and_fastest_disagree_on_a_long_route(client):
    cheap = search(client, "Dortmund", "München", preset="cheapest")
    fast = search(client, "Dortmund", "München", preset="fastest")
    assert cheap["options"][0]["total_cents"] <= fast["options"][0]["total_cents"]


def test_raising_value_of_time_never_promotes_the_slowest_option(client):
    low = search(client, "Köln", "Berlin", preset="balanced", vot_cents=200)
    high = search(client, "Köln", "Berlin", preset="balanced", vot_cents=12000)
    slowest = max(o["door_to_door_minutes"] for o in low["options"])
    assert high["options"][0]["door_to_door_minutes"] < slowest


# ------------------------------------------------------------ traveller flags

def test_checking_a_bag_makes_flying_slower_and_dearer(client, with_flights):
    without = mode(search(client, "München", "Hamburg", preset="fastest"), "air")
    with_bag = mode(search(client, "München", "Hamburg", preset="fastest",
                           checked_bag="true"), "air")
    assert with_bag["door_to_door_minutes"] > without["door_to_door_minutes"]
    assert with_bag["total_cents"] > without["total_cents"]


def test_deutschlandticket_option_is_labelled_covered_not_merely_zero(client):
    """Since MOTIS rarely carries fares, most options price at zero. A
    Deutschlandticket option therefore has to be identified by its stated
    reason, not by its total, or the assertion means nothing."""
    body = search(client, "Frankfurt am Main", "Stuttgart",
                  deutschlandticket="true", preset="cheapest")
    covered = [o for o in body["options"]
               if any("Deutschlandticket" in c["label"] for c in o["cost_lines"])]
    assert covered, "no option identified as covered by the pass"
    assert covered[0]["mode"] == "rail_regional"


def test_missing_fares_are_declared_rather_than_guessed(client):
    """The honest failure mode: say the feed has no fare, do not invent one."""
    body = search(client, "Köln", "Berlin")
    unpriced = [o for o in body["options"] if o["total_cents"] == 0
                and o["mode"].startswith("rail")]
    for o in unpriced:
        assert o["confidence"] != "live"
        assert any("fare" in n.lower() for n in o["notes"])


def test_deutschlandticket_wins_on_cheapest_but_not_on_fastest(client):
    cheap = search(client, "Frankfurt am Main", "Stuttgart",
                   deutschlandticket="true", preset="cheapest")
    fast = search(client, "Frankfurt am Main", "Stuttgart",
                  deutschlandticket="true", preset="fastest")
    assert cheap["options"][0]["total_cents"] == 0
    assert fast["options"][0]["mode"] != "rail_regional"


# ------------------------------------------------------------- invariants

@pytest.mark.parametrize("pair", list(RAIL_TIMES))
def test_no_route_ever_reports_a_ride_longer_than_its_envelope(client, pair):
    body = search(client, *pair)
    for opt in body["options"]:
        ride = sum(l["minutes"] for l in opt["legs"] if l["kind"] == "ride")
        assert opt["door_to_door_minutes"] >= ride, (pair, opt["mode"])


@pytest.mark.parametrize("pair", list(RAIL_TIMES))
def test_every_option_declares_whether_its_fare_is_real(client, pair):
    body = search(client, *pair)
    for opt in body["options"]:
        assert opt["confidence"] in {"live", "schedule", "modelled"}
        if opt["mode"] == "air":
            assert opt["confidence"] == "modelled"


def test_flying_always_emits_more_than_taking_the_train(client, with_flights):
    body = search(client, "München", "Hamburg")
    assert mode(body, "air")["co2_g"] > mode(body, "rail")["co2_g"] * 3
