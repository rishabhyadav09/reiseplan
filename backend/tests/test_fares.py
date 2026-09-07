"""Fare bands. Anchored to published DB tariff facts, not to my output.

If a change makes one of these fail, the model has drifted away from what
Deutsche Bahn actually charges, which is the only thing that makes an
estimate defensible.
"""

import pytest

from app.fares import estimate

# Dortmund - Frankfurt is about 221 km by rail.
DOFRA = 221


def band(km=DOFRA, days=21, country="DE", long_distance=True, bahncard=0):
    return estimate(km=km, country=country, days_ahead=days,
                    long_distance=long_distance, bahncard=bahncard)


def test_never_returns_the_advertised_floor_as_an_upper_bound():
    b = band(days=90)
    assert b.low_cents >= 1790, "DB's cheapest national Sparpreis is EUR 17.90"


def test_the_band_brackets_the_real_flexpreis():
    """Dortmund-Frankfurt Flexpreis is about EUR 77. A same-day traveller
    should be quoted close to it, never far above."""
    b = band(days=0)
    assert 5000 <= b.high_cents <= 9000, b.label()


def test_booking_earlier_is_never_dearer():
    prices = [band(days=d).typical_cents for d in (90, 60, 30, 14, 7, 3, 0)]
    assert prices == sorted(prices), prices


def test_the_band_narrows_as_departure_approaches():
    early = band(days=60)
    late = band(days=2)
    assert (late.high_cents - late.low_cents) < (early.high_cents - early.low_cents)


def test_longer_journeys_cost_more():
    assert band(km=584).typical_cents > band(km=221).typical_cents


def test_a_bahncard_50_halves_the_band():
    full, discounted = band(), band(bahncard=50)
    assert discounted.typical_cents == pytest.approx(full.typical_cents / 2, rel=0.02)


def test_regional_fares_are_a_single_price_not_a_range():
    b = band(km=45, long_distance=False)
    assert b.low_cents == b.high_cents
    assert "€" in b.label() and "–" not in b.label()


def test_a_tram_hop_is_not_priced_at_all():
    """Better to say nothing than to invent a fare for a 2 km ride."""
    assert estimate(km=2, country="DE", days_ahead=7, long_distance=False) is None


def test_switzerland_is_dearer_than_poland_for_the_same_distance():
    ch = estimate(km=300, country="CH", days_ahead=21, long_distance=True)
    pl = estimate(km=300, country="PL", days_ahead=21, long_distance=True)
    assert ch.typical_cents > pl.typical_cents * 2


def test_an_unknown_country_falls_back_rather_than_crashing():
    assert estimate(km=300, country="ZZ", days_ahead=21, long_distance=True) is not None


def test_the_label_is_a_range_a_traveller_can_read():
    assert band().label().startswith("€")
    assert "–" in band().label()
