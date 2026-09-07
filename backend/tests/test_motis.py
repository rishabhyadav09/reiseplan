"""MOTIS adapter: parsing, mode classification, and fare honesty.

Fixtures are shaped from the published MOTIS v5 schema (openapi.yaml,
motis-project/motis) rather than invented.
"""

from datetime import UTC, datetime, timedelta

from app.domain import Confidence, Mode
from app.providers.motis import itinerary_from_motis

T0 = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)


def leg(mode, mins, *, start_offset=0, name=None, dist_m=0, to="Somewhere"):
    dep = T0 + timedelta(minutes=start_offset)
    return {
        "mode": mode,
        "startTime": dep.isoformat(),
        "endTime": (dep + timedelta(minutes=mins)).isoformat(),
        "distance": dist_m,
        "routeShortName": name,
        "to": {"name": to},
        "from": {"name": "Here"},
    }


def itin(legs, duration_min, **extra):
    return {
        "startTime": T0.isoformat(),
        "endTime": (T0 + timedelta(minutes=duration_min)).isoformat(),
        "duration": duration_min * 60,
        "transfers": extra.pop("transfers", 0),
        "id": "x",
        "legs": legs,
        **extra,
    }


def test_a_walk_train_walk_journey_parses_door_to_door():
    it = itinerary_from_motis(itin([
        leg("WALK", 9, to="Dortmund Hbf"),
        leg("HIGHSPEED_RAIL", 135, start_offset=20, name="ICE 613",
            dist_m=221_000, to="Frankfurt(Main)Hbf"),
        leg("WALK", 7, start_offset=155, to="the office"),
    ], 162))
    assert it is not None
    assert it.mode is Mode.RAIL
    kinds = [x.kind.value for x in it.legs]
    assert kinds[0] == "access" and kinds[-1] == "egress"
    # 9 walk + 11 wait + 135 ride + 7 walk
    assert it.door_to_door_minutes == 162.0


def test_night_rail_is_native_not_a_name_guess():
    """DB needed an 'NJ' prefix heuristic. MOTIS says so outright."""
    it = itinerary_from_motis(itin([
        leg("NIGHT_RAIL", 515, name="NJ 40491", dist_m=584_000)], 515))
    assert it.mode is Mode.NIGHT_RAIL
    assert any("Hotel night saved" in c.label for c in it.cost_lines)


def test_a_coach_leg_is_a_coach_journey():
    it = itinerary_from_motis(itin([
        leg("COACH", 250, name="FlixBus 001", dist_m=231_000)], 250))
    assert it.mode is Mode.COACH


def test_a_tram_feeder_does_not_downgrade_a_long_distance_journey():
    it = itinerary_from_motis(itin([
        leg("TRAM", 8, dist_m=3_000),
        leg("HIGHSPEED_RAIL", 130, start_offset=15, dist_m=221_000),
    ], 145, transfers=1))
    assert it.mode is Mode.RAIL


def test_tram_only_journeys_are_regional():
    it = itinerary_from_motis(itin([leg("TRAM", 22, dist_m=7_000)], 22))
    assert it.mode is Mode.RAIL_REGIONAL


def test_long_distance_time_is_productive_but_a_short_tram_is_not():
    it = itinerary_from_motis(itin([
        leg("TRAM", 8, dist_m=3_000),
        leg("HIGHSPEED_RAIL", 130, start_offset=15, dist_m=221_000),
    ], 145))
    assert it.productive_minutes == 130.0


def test_missing_fare_data_says_so_instead_of_inventing_one():
    it = itinerary_from_motis(itin([leg("HIGHSPEED_RAIL", 130, dist_m=221_000)], 130))
    assert it.total_cents == 0
    assert it.confidence is Confidence.SCHEDULE
    assert any("no fare data" in n.lower() for n in it.notes)


def test_a_published_gtfs_fare_is_used_and_marked_live():
    payload = itin([leg("REGIONAL_RAIL", 40, dist_m=45_000)], 40)
    payload["fareTransfers"] = [
        {"effectiveFareLegProducts": [[{"amount": 12.40, "currency": "EUR"}]]}
    ]
    it = itinerary_from_motis(payload)
    assert it.total_cents == 1240
    assert it.confidence is Confidence.LIVE


def test_deutschlandticket_zeroes_a_regional_journey():
    it = itinerary_from_motis(
        itin([leg("REGIONAL_RAIL", 152, dist_m=180_000)], 152),
        deutschlandticket=True)
    assert it.total_cents == 0
    assert it.mode is Mode.RAIL_REGIONAL


def test_waiting_between_legs_lands_in_the_envelope():
    it = itinerary_from_motis(itin([
        leg("REGIONAL_RAIL", 30, dist_m=25_000),
        leg("HIGHSPEED_RAIL", 90, start_offset=48, dist_m=180_000),
    ], 138, transfers=1))
    assert any(x.kind.value == "transfer" for x in it.legs)
    assert it.door_to_door_minutes == 138.0


def test_malformed_input_returns_none():
    assert itinerary_from_motis({"legs": []}) is None
    assert itinerary_from_motis({"legs": [{"mode": "RAIL"}]}) is None


def test_transit_legs_get_emissions_from_coordinates_not_a_missing_field():
    """MOTIS omits `distance` on transit legs. Reporting 0 kg for a 220 km ICE
    would quietly break the low-carbon preset."""
    dep = T0
    it = itinerary_from_motis(itin([{
        "mode": "HIGHSPEED_RAIL", "routeShortName": "ICE 613",
        "startTime": dep.isoformat(),
        "endTime": (dep + timedelta(minutes=135)).isoformat(),
        "from": {"name": "Dortmund Hbf", "lat": 51.5177, "lon": 7.4592},
        "to": {"name": "Frankfurt(Main)Hbf", "lat": 50.1070, "lon": 8.6638},
    }], 135))
    assert it.co2_g > 4000, "a 220 km train cannot emit nothing"
    assert it.co2_g < 12000


def test_distance_field_is_still_preferred_when_present():
    it = itinerary_from_motis(itin([leg("COACH", 250, dist_m=231_000)], 250))
    assert 6000 < it.co2_g < 7500   # 231 km x 29 g/pkm
