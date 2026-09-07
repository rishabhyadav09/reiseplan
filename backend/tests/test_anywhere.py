"""Anywhere search. Pure, so every assertion is about the model itself."""

from app.anywhere import MIN_DISTANCE_KM, search
from app.destinations import DESTINATIONS

DORTMUND = {"origin_lat": 51.5136, "origin_lon": 7.4653, "origin_country": "DE"}


def test_results_are_ordered_cheapest_first():
    rows = search(**DORTMUND, days_ahead=21, limit=30)
    fares = [o.fare_typical_cents for o in rows]
    assert fares == sorted(fares)


def test_nothing_closer_than_the_minimum_distance_is_offered():
    """Under 100 km is a commute, not a trip worth inspiring someone about."""
    for o in search(**DORTMUND, days_ahead=21, limit=100):
        assert o.km >= MIN_DISTANCE_KM


def test_nearby_cities_are_cheaper_than_distant_ones():
    rows = {o.destination.name: o for o in search(**DORTMUND, days_ahead=21, limit=100)}
    assert rows["Amsterdam"].fare_typical_cents < rows["Roma"].fare_typical_cents
    assert rows["Amsterdam"].hours < rows["Roma"].hours


def test_islands_are_offered_by_air_because_rail_is_impractical():
    rows = {o.destination.name: o for o in search(**DORTMUND, days_ahead=21, limit=100)}
    assert rows["Dublin"].mode == "flight"
    assert rows["Dublin"].note is not None


def test_close_continental_cities_are_offered_by_rail_not_air():
    rows = {o.destination.name: o for o in search(**DORTMUND, days_ahead=21, limit=100)}
    for city in ("Amsterdam", "Brussel", "Frankfurt am Main"):
        assert rows[city].mode == "rail", city


def test_a_budget_filter_excludes_everything_above_it():
    rows = search(**DORTMUND, days_ahead=21, max_fare_cents=5000, limit=100)
    assert rows
    for o in rows:
        assert o.fare_low_cents <= 5000


def test_a_time_filter_excludes_everything_slower():
    rows = search(**DORTMUND, days_ahead=21, max_hours=4.0, limit=100)
    assert rows
    for o in rows:
        assert o.hours <= 4.0


def test_booking_further_ahead_never_costs_more():
    early = search(**DORTMUND, days_ahead=90, limit=10)
    late = search(**DORTMUND, days_ahead=2, limit=10)
    assert early[0].fare_typical_cents <= late[0].fare_typical_cents


def test_a_bahncard_reduces_rail_fares():
    plain = {o.destination.name: o for o in search(**DORTMUND, days_ahead=21, limit=100)}
    card = {o.destination.name: o for o in
            search(**DORTMUND, days_ahead=21, bahncard=50, limit=100)}
    assert card["Amsterdam"].fare_typical_cents < plain["Amsterdam"].fare_typical_cents


def test_flying_always_emits_more_than_the_train():
    rows = {o.destination.name: o for o in search(**DORTMUND, days_ahead=21, limit=100)}
    assert rows["Dublin"].co2_kg > rows["Amsterdam"].co2_kg * 3


def test_searching_from_a_destination_never_returns_itself():
    berlin = next(d for d in DESTINATIONS if d.name == "Berlin")
    rows = search(origin_lat=berlin.lat, origin_lon=berlin.lon,
                  origin_country="DE", days_ahead=21, limit=100)
    assert all(o.destination.name != "Berlin" for o in rows)


def test_it_is_fast_enough_to_run_on_every_keystroke():
    import time
    t0 = time.perf_counter()
    for _ in range(20):
        search(**DORTMUND, days_ahead=21, limit=40)
    assert (time.perf_counter() - t0) / 20 < 0.02, "cheap pass must stay cheap"
