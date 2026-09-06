"""Generalised-cost ranking.

This module is deliberately pure: no network, no clock, no config lookups.
Everything it needs arrives as arguments, so the whole ranking model is
testable without a single mock. If you port the service to Go, this is the
file to port first and the only one whose behaviour must stay identical.

The model is standard transport economics. A traveller's real cost of a
journey is not the fare; it is

    fare
  + time spent, priced at their value of time and weighted by how
    unpleasant that particular time is
  - time they can actually work, credited back
  + carbon, at whatever price they put on it
  + a fixed penalty per hassle point (transfers, security, luggage)

Lower is better. Ranking by this instead of by fare is the entire reason
this service exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import Itinerary, LegKind, Mode

# How unpleasant an hour is, per mode, relative to an hour of ordinary life.
# An hour queueing at Düsseldorf security costs more than an hour in an ICE
# seat with a table. A sleeper berth is nearly free because you were going to
# be unconscious anyway.
DISCOMFORT: dict[Mode, float] = {
    Mode.RAIL: 0.85,
    Mode.RAIL_REGIONAL: 1.00,
    Mode.NIGHT_RAIL: 0.35,
    Mode.COACH: 1.25,
    Mode.AIR: 1.15,
}

# Hassle points by leg kind, charged once per occurrence.
HASSLE_POINTS: dict[LegKind, float] = {
    LegKind.ACCESS: 0.5,
    LegKind.RIDE: 0.0,
    LegKind.TRANSFER: 1.2,
    LegKind.CHECKIN: 3.0,
    LegKind.DISEMBARK: 1.0,
    LegKind.EGRESS: 0.5,
}

HASSLE_CENTS = 350  # what one hassle point costs a median traveller
BAG_HASSLE_POINTS = 1.5


@dataclass(frozen=True, slots=True)
class Weights:
    """A traveller's preferences, expressed in money."""

    vot_cents_per_hour: int      # value of time
    carbon_cents_per_kg: int     # internal carbon price
    productivity: float          # 0 = laptop time worthless, 1.4 = very valuable

    def __post_init__(self) -> None:
        if self.vot_cents_per_hour < 0:
            raise ValueError("value of time cannot be negative")
        if not 0.0 <= self.productivity <= 3.0:
            raise ValueError("productivity multiplier out of range")


PRESETS: dict[str, Weights] = {
    "cheapest": Weights(400, 5, 0.0),
    "fastest": Weights(4500, 5, 0.3),
    "balanced": Weights(1600, 15, 0.5),
    "laptop": Weights(2000, 15, 1.4),
    "low_carbon": Weights(1200, 90, 0.7),
}


@dataclass(frozen=True, slots=True)
class Scored:
    itinerary: Itinerary
    generalized_cents: int
    time_cents: int
    productivity_credit_cents: int
    carbon_cents: int
    hassle_cents: int
    match: int  # 0-100, relative to the best option in this result set


def hassle_points(it: Itinerary, checked_bag: bool) -> float:
    points = sum(HASSLE_POINTS[leg.kind] for leg in it.legs)
    if checked_bag and it.mode is Mode.AIR:
        points += BAG_HASSLE_POINTS
    return points


def generalized_cost_cents(
    it: Itinerary, w: Weights, *, checked_bag: bool = False
) -> tuple[int, dict[str, int]]:
    """Return total generalised cost and the components that built it."""
    hours = it.door_to_door_minutes / 60.0
    time_cents = round(hours * w.vot_cents_per_hour * DISCOMFORT[it.mode])

    credit = round(
        (it.productive_minutes / 60.0) * w.vot_cents_per_hour * w.productivity * 0.6
    )
    # You can never be credited more than the time cost itself.
    credit = min(credit, time_cents)

    carbon_cents = round((it.co2_g / 1000.0) * w.carbon_cents_per_kg)
    hassle_cents = round(hassle_points(it, checked_bag) * HASSLE_CENTS)

    total = it.total_cents + time_cents - credit + carbon_cents + hassle_cents
    parts = {
        "fare": it.total_cents,
        "time": time_cents,
        "productivity_credit": -credit,
        "carbon": carbon_cents,
        "hassle": hassle_cents,
    }
    return total, parts


def rank(
    itineraries: list[Itinerary], w: Weights, *, checked_bag: bool = False
) -> list[Scored]:
    """Sort by generalised cost, cheapest first, and attach a match score."""
    if not itineraries:
        return []

    rows: list[Scored] = []
    for it in itineraries:
        total, parts = generalized_cost_cents(it, w, checked_bag=checked_bag)
        rows.append(
            Scored(
                itinerary=it,
                generalized_cents=total,
                time_cents=parts["time"],
                productivity_credit_cents=parts["productivity_credit"],
                carbon_cents=parts["carbon"],
                hassle_cents=parts["hassle"],
                match=0,
            )
        )

    rows.sort(key=lambda r: r.generalized_cents)
    best = max(1, rows[0].generalized_cents)
    return [
        Scored(
            itinerary=r.itinerary,
            generalized_cents=r.generalized_cents,
            time_cents=r.time_cents,
            productivity_credit_cents=r.productivity_credit_cents,
            carbon_cents=r.carbon_cents,
            hassle_cents=r.hassle_cents,
            match=max(1, min(100, round(100 * best / max(1, r.generalized_cents)))),
        )
        for r in rows
    ]
