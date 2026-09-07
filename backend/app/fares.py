"""Fare estimation as a range, not a number.

MOTIS gives us schedules; GTFS rarely carries fares. Showing EUR 0.00 makes
the app unusable, and showing an invented exact price makes it dishonest. A
band is both truthful and decision-useful: nobody needs to know a ticket is
EUR 42.50, they need to know it is not EUR 200.

Why this is defensible for rail when it was not for flights: German rail is a
published tariff. Flexpreis is roughly linear in distance, Sparpreis is a
quota-limited discount off it, and DB advertises fares as "ab EUR 17,90"
themselves. Airline pricing is dynamic yield management and cannot be
modelled from distance at all.

Pure module: no I/O, no clock. Everything needed arrives as arguments, so the
whole tariff is testable and a second country is a new dataclass rather than
a new code path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tariff:
    """One country's long-distance rail pricing, in cents."""

    name: str
    flex_base_cents: int          # boarding component
    flex_cents_per_km: int        # distance component of the flexible fare
    saver_floor_cents: int        # the advertised "from" price
    saver_share_min: float        # cheapest saver as a share of flex
    saver_share_max: float        # dearest saver as a share of flex
    regional_cents_per_km: int    # local/regional services
    regional_floor_cents: int


TARIFFS: dict[str, Tariff] = {
    # Sparpreis from EUR 17.90, Flexpreis ~EUR 0.28/km. Dortmund-Frankfurt
    # (~220 km) models to a EUR 18-72 band; the real Flexpreis is about EUR 77.
    "DE": Tariff("Deutsche Bahn", 1000, 28, 1790, 0.25, 0.75, 22, 290),
    "AT": Tariff("ÖBB", 900, 24, 1490, 0.28, 0.80, 20, 260),
    "CH": Tariff("SBB", 1200, 38, 2900, 0.45, 0.95, 34, 320),
    "FR": Tariff("SNCF", 1200, 26, 1900, 0.30, 0.85, 21, 280),
    "IT": Tariff("Trenitalia", 900, 20, 1290, 0.25, 0.80, 17, 250),
    "NL": Tariff("NS", 1000, 25, 1600, 0.55, 1.00, 24, 290),
    "ES": Tariff("Renfe", 1100, 24, 1900, 0.30, 0.85, 19, 260),
    "PL": Tariff("PKP", 600, 14, 900, 0.35, 0.90, 12, 180),
    "CZ": Tariff("ČD", 600, 13, 800, 0.35, 0.90, 11, 170),
    "BE": Tariff("SNCB", 900, 22, 1300, 0.60, 1.00, 21, 260),
}
DEFAULT_TARIFF = TARIFFS["DE"]

# How much of the saver range is realistically available, by how far ahead you
# book. Sparpreis contingents sell out; a same-day traveller pays flex.
_ADVANCE_CURVE = [(60, 0.00), (30, 0.12), (21, 0.25), (14, 0.42),
                  (7, 0.60), (3, 0.80), (1, 0.92), (0, 1.00)]


def _advance_position(days_ahead: int) -> float:
    """0.0 = cheapest saver plausible, 1.0 = flexible fare only."""
    for i, (days, pos) in enumerate(_ADVANCE_CURVE):
        if days_ahead >= days:
            return pos
        if i + 1 < len(_ADVANCE_CURVE):
            nd, npos = _ADVANCE_CURVE[i + 1]
            if days_ahead > nd:
                span = days - nd
                return npos + (pos - npos) * (days_ahead - nd) / span
    return 1.0


@dataclass(frozen=True, slots=True)
class FareBand:
    low_cents: int
    typical_cents: int
    high_cents: int
    basis: str          # shown to the user, so it must be plain language

    def label(self) -> str:
        if self.low_cents == self.high_cents:
            return f"€{self.low_cents / 100:.2f}"
        return f"€{self.low_cents / 100:.0f}–{self.high_cents / 100:.0f}"


def estimate(
    *,
    km: float,
    country: str,
    days_ahead: int,
    long_distance: bool,
    bahncard: int = 0,
) -> FareBand | None:
    """Estimate a fare band. Returns None when the distance is too short to
    model meaningfully — better to say nothing than to guess at a tram fare."""
    if km < 5:
        return None

    tariff = TARIFFS.get(country.upper(), DEFAULT_TARIFF)

    if not long_distance:
        fare = max(tariff.regional_floor_cents,
                   round(tariff.regional_cents_per_km * km))
        return FareBand(fare, fare, fare, f"{tariff.name} regional fare")

    flex = tariff.flex_base_cents + round(tariff.flex_cents_per_km * km)
    pos = _advance_position(days_ahead)

    # The available saver window narrows toward the flexible fare as the
    # departure approaches.
    share_low = tariff.saver_share_min + (1.0 - tariff.saver_share_min) * pos
    share_high = tariff.saver_share_max + (1.0 - tariff.saver_share_max) * pos

    low = max(tariff.saver_floor_cents, round(flex * share_low))
    high = min(flex, max(low, round(flex * share_high)))
    typical = round((low + high) / 2)

    if bahncard in (25, 50):
        factor = 0.75 if bahncard == 25 else 0.50
        low, typical, high = (round(v * factor) for v in (low, typical, high))

    when = ("booking well ahead" if pos < 0.2
            else "booking a few weeks out" if pos < 0.5
            else "booking close to departure")
    return FareBand(low, typical, high, f"{tariff.name} tariff, {when}")
