from datetime import datetime, timedelta, timezone

import pytest

from app.domain import Confidence, CostLine, Itinerary, Leg, LegKind, Mode
from app.scoring import PRESETS, Weights, generalized_cost_cents, rank

T0 = datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)


def make(mode, minutes, cents, *, productive=0.0, co2_g=0, legs=None):
    legs = legs or (
        Leg(LegKind.ACCESS, "access", 12.0),
        Leg(LegKind.RIDE, "ride", minutes - 24.0, productive=productive > 0),
        Leg(LegKind.EGRESS, "egress", 12.0),
    )
    return Itinerary(
        mode=mode,
        provider="test",
        depart=T0,
        arrive=T0 + timedelta(minutes=minutes),
        legs=legs,
        cost_lines=(CostLine("fare", cents),),
        co2_g=co2_g,
        transfers=0,
        confidence=Confidence.MODELLED,
    )


def test_door_to_door_counts_every_leg_including_waiting():
    it = make(Mode.RAIL, 0, 0, legs=(
        Leg(LegKind.ACCESS, "walk", 9.0),
        Leg(LegKind.RIDE, "ICE", 245.0, productive=True),
        Leg(LegKind.TRANSFER, "waiting", 18.0),
        Leg(LegKind.RIDE, "RE", 22.0, productive=False),
        Leg(LegKind.EGRESS, "tram", 11.0),
    ))
    assert it.door_to_door_minutes == 305.0
    assert it.productive_minutes == 245.0


def test_cheapest_preset_picks_the_cheap_slow_option():
    coach = make(Mode.COACH, 420, 1900)
    air = make(Mode.AIR, 280, 14500)
    ranked = rank([air, coach], PRESETS["cheapest"])
    assert ranked[0].itinerary.mode is Mode.COACH


def test_fastest_preset_flips_to_the_expensive_quick_option():
    coach = make(Mode.COACH, 420, 1900)
    air = make(Mode.AIR, 280, 14500)
    ranked = rank([air, coach], PRESETS["fastest"])
    assert ranked[0].itinerary.mode is Mode.AIR


def test_laptop_preset_can_beat_a_faster_flight_with_a_workable_train():
    train = make(Mode.RAIL, 300, 6900, productive=1.0)
    air = make(Mode.AIR, 260, 12000)
    assert rank([air, train], PRESETS["laptop"])[0].itinerary.mode is Mode.RAIL


def test_carbon_price_changes_the_answer():
    train = make(Mode.RAIL, 320, 7900, co2_g=9_000)
    air = make(Mode.AIR, 270, 7500, co2_g=115_000)
    assert rank([air, train], PRESETS["low_carbon"])[0].itinerary.mode is Mode.RAIL


def test_productivity_credit_never_exceeds_the_time_cost():
    it = make(Mode.RAIL, 600, 5000, productive=1.0)
    w = Weights(vot_cents_per_hour=1000, carbon_cents_per_kg=0, productivity=3.0)
    total, parts = generalized_cost_cents(it, w)
    assert parts["time"] + parts["productivity_credit"] >= 0
    assert total >= it.total_cents


def test_air_is_charged_extra_hassle_when_a_bag_is_checked():
    air = make(Mode.AIR, 280, 9000)
    w = PRESETS["balanced"]
    without, _ = generalized_cost_cents(air, w, checked_bag=False)
    with_bag, _ = generalized_cost_cents(air, w, checked_bag=True)
    assert with_bag > without


def test_match_score_is_100_for_the_winner_and_lower_for_the_rest():
    ranked = rank([make(Mode.COACH, 420, 1900), make(Mode.AIR, 280, 14500)], PRESETS["balanced"])
    assert ranked[0].match == 100
    assert ranked[1].match < 100


def test_empty_input_is_not_an_error():
    assert rank([], PRESETS["balanced"]) == []


def test_negative_value_of_time_is_rejected():
    with pytest.raises(ValueError):
        Weights(vot_cents_per_hour=-1, carbon_cents_per_kg=0, productivity=0.5)
