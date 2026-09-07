"""The Anywhere search: one origin, every destination worth considering.

The cheap pass. No upstream calls at all — distance is geometry, fare comes
from the tariff model, and time comes from a corridor-speed estimate. That is
what makes this feasible: Skyscanner's Everywhere needs a cached price for
every origin-destination pair, whereas we compute ours, so a few hundred
destinations cost roughly a millisecond and zero quota.

The estimates here are coarse on purpose. This is a shortlisting tool: it
exists to answer "where could I go this weekend for under EUR 80", not to
tell anyone which train to catch. Tapping a result runs the real MOTIS query.

Pure module. No I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from .destinations import DESTINATIONS, Destination
from .fares import estimate
from .geo import CO2_G_PER_PKM, haversine_km

# Effective door-to-door rail speed on each national network, km/h. Not top
# speed: France's LGV network averages far better than Germany's stop-heavy
# ICE routes, and the Baltics have no high-speed line at all.
RAIL_SPEED = {
    "FR": 158, "ES": 162, "IT": 150, "DE": 112, "NL": 120, "BE": 120,
    "AT": 104, "CH": 100, "GB": 130, "DK": 112, "SE": 100, "NO": 88,
    "FI": 95, "PL": 92, "CZ": 88, "HU": 85, "SK": 82, "SI": 70, "HR": 62,
    "RO": 60, "BG": 55, "LV": 58, "EE": 55, "LT": 58, "PT": 95, "LU": 100,
    "GR": 60, "IE": 70,
}
DEFAULT_SPEED = 95

# Rail route length versus straight line, plus the awkward crossings.
BASE_DETOUR = 1.22
REGION = {
    "DE": "C", "AT": "C", "CH": "C", "NL": "C", "BE": "C", "LU": "C",
    "FR": "W", "GB": "W", "IE": "X", "IT": "S", "ES": "I", "PT": "I",
    "DK": "N", "SE": "N", "NO": "N", "FI": "F",
    "CZ": "E", "PL": "E", "HU": "E", "SK": "E", "SI": "E",
    "HR": "B", "RO": "B", "BG": "B", "GR": "B",
    "LV": "L", "EE": "L", "LT": "L",
}
# Regions where rail is impractical or absurdly indirect from the continent.
RAIL_IMPRACTICAL = {"X", "F", "L"}
EXTRA_DETOUR = {"I": 1.35, "B": 1.50, "N": 1.25, "W": 1.10}

MIN_DISTANCE_KM = 100.0     # below this it is a commute, not a trip
FLIGHT_MIN_KM = 400.0       # nobody flies shorter, and the door-to-door loses


@dataclass(frozen=True, slots=True)
class Option:
    destination: Destination
    km: float
    mode: str                 # "rail" or "flight"
    hours: float              # door to door, estimated
    fare_low_cents: int
    fare_high_cents: int
    fare_typical_cents: int
    co2_kg: float
    reachable: bool
    note: str | None = None

    @property
    def fare_label(self) -> str:
        if self.fare_low_cents == self.fare_high_cents:
            return f"€{self.fare_low_cents / 100:.0f}"
        return f"€{self.fare_low_cents / 100:.0f}–{self.fare_high_cents / 100:.0f}"


def _rail_detour(a: str, b: str) -> float:
    ra, rb = REGION.get(a, "C"), REGION.get(b, "C")
    if ra == rb:
        return BASE_DETOUR
    for region in (ra, rb):
        if region in EXTRA_DETOUR:
            return BASE_DETOUR * EXTRA_DETOUR[region]
    return BASE_DETOUR * 1.12


def _rail_hours(km: float, a: str, b: str, quality: float) -> float:
    speed = (RAIL_SPEED.get(a, DEFAULT_SPEED) + RAIL_SPEED.get(b, DEFAULT_SPEED)) / 2
    # A poorly connected destination means changes and waiting, not slow track.
    speed *= 0.75 + 0.25 * quality
    route_km = km * _rail_detour(a, b)
    changes = 0 if km < 330 else 1 if km < 700 else 2 if km < 1200 else 3
    return route_km / speed + 0.6 + changes * 0.45


def _flight_hours(km: float) -> float:
    """Door to door: getting out to the airport, the queue, the flight, and
    the ride into town at the far end. The bit booking sites never show."""
    block = 0.45 + km / 780
    return 1.1 + 1.2 + block + 0.4 + 0.7


def _flight_fare_cents(km: float, days_ahead: int) -> int:
    base = 3200 + km * 5.5
    mult = (0.85 if days_ahead >= 60 else 1.00 if days_ahead >= 30
            else 1.25 if days_ahead >= 14 else 1.7 if days_ahead >= 7 else 2.4)
    return max(3500, round(base * mult))


def search(
    *,
    origin_lat: float,
    origin_lon: float,
    origin_country: str = "DE",
    days_ahead: int = 21,
    max_fare_cents: int | None = None,
    max_hours: float | None = None,
    bahncard: int = 0,
    limit: int = 40,
) -> list[Option]:
    """Rank destinations by fare, cheapest first. Pure and fast."""
    out: list[Option] = []

    for dest in DESTINATIONS:
        km = haversine_km(origin_lat, origin_lon, dest.lat, dest.lon)
        if km < MIN_DISTANCE_KM:
            continue

        rail_blocked = REGION.get(dest.country) in RAIL_IMPRACTICAL
        options: list[Option] = []

        if not rail_blocked:
            hours = _rail_hours(km, origin_country, dest.country, dest.rail)
            band = estimate(km=km * _rail_detour(origin_country, dest.country),
                            country=dest.country, days_ahead=days_ahead,
                            long_distance=True, bahncard=bahncard)
            if band:
                options.append(Option(
                    dest, km, "rail", hours,
                    band.low_cents, band.high_cents, band.typical_cents,
                    km * _rail_detour(origin_country, dest.country)
                    * CO2_G_PER_PKM["rail_long"] / 1000,
                    reachable=True,
                ))

        if km >= FLIGHT_MIN_KM or rail_blocked:
            fare = _flight_fare_cents(km, days_ahead)
            options.append(Option(
                dest, km, "flight", _flight_hours(km),
                round(fare * 0.7), round(fare * 1.6), fare,
                (km * CO2_G_PER_PKM["air_domestic"] + 8000) / 1000,
                reachable=True,
                note="No practical rail route" if rail_blocked else None,
            ))

        if not options:
            continue

        # Whichever mode is cheaper is the one worth showing on a shortlist.
        best = min(options, key=lambda o: o.fare_typical_cents)
        if max_fare_cents is not None and best.fare_low_cents > max_fare_cents:
            continue
        if max_hours is not None and best.hours > max_hours:
            continue
        out.append(best)

    out.sort(key=lambda o: (o.fare_typical_cents, o.hours))
    return out[:limit]
