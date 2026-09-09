"""Flight adapter.

Two honest caveats up front.

First, there is no longer a free real-fare feed for a POC. Amadeus shut its
Self-Service tier down on 17 July 2026 and Kiwi's Tequila closed to new
developers the same year. Duffel's test mode returns sandbox data from a
fictional airline, so its prices are useless for ranking. The fare here is
therefore *modelled* and every itinerary is labelled `MODELLED` so the UI can
say so. Swap in `DuffelProvider` once you have live-mode credentials; the
interface does not change.

Second, and more usefully: the access and egress legs are NOT modelled. They
come from the same DB API as the trains, routed from the traveller's actual
coordinates to the airport's rail station. That is the whole point. A Munich
flight from Dortmund looks fine until you price the 70 minutes to Düsseldorf
airport at both ends, and that number is real here.

German domestic aviation has contracted sharply, so the route table is
explicit rather than distance-derived. Returning "no flight exists" is a
correct and valuable answer.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from ..catalog import AIRPORTS, find_city
from ..domain import (
    Confidence,
    CostLine,
    Itinerary,
    Leg,
    LegKind,
    Mode,
    Place,
    PlanRequest,
    ProviderResult,
)
from ..geo import AIR_FIXED_G, CO2_G_PER_PKM, haversine_km
from .db_rail import fetch_journeys, journey_to_itinerary, resolve_station

log = logging.getLogger(__name__)

# Domestic routes with scheduled service. Unordered pairs.
DOMESTIC_ROUTES: set[frozenset[str]] = {
    frozenset(p)
    for p in [
        ("FRA", "BER"), ("FRA", "MUC"), ("FRA", "HAM"), ("FRA", "DRS"),
        ("FRA", "LEJ"), ("FRA", "NUE"), ("FRA", "BRE"),
        ("MUC", "BER"), ("MUC", "HAM"), ("MUC", "DUS"), ("MUC", "CGN"),
        ("MUC", "BRE"), ("MUC", "HAJ"), ("MUC", "LEJ"), ("MUC", "DRS"),
        ("MUC", "FMO"),
        ("BER", "DUS"), ("BER", "CGN"), ("BER", "STR"), ("BER", "NUE"),
        ("HAM", "STR"),
    ]
}

CHECKIN_MIN_CARRYON = 55      # domestic, no passport control
CHECKIN_MIN_CHECKED = 80
DISEMBARK_MIN_CARRYON = 12
DISEMBARK_MIN_CHECKED = 28
CHECKED_BAG_CENTS = 3000


def _advance_purchase_multiplier(days: int) -> float:
    curve = [(60, 0.85), (30, 1.00), (21, 1.15), (14, 1.40), (7, 1.85), (3, 2.40), (0, 2.90)]
    for i, (d, m) in enumerate(curve):
        if days >= d:
            return m
        if i + 1 < len(curve):
            nd, nm = curve[i + 1]
            if days > nd:
                return nm + (m - nm) * (days - nd) / (d - nd)
    return curve[-1][1]


def _block_minutes(km: float) -> float:
    """Gate to gate, including taxi, climb and descent."""
    return 27 + km / 11.5


def _fare_cents(km: float, days: int) -> int:
    base = 5500 + km * 9.0            # Lufthansa-weighted domestic pricing
    return max(5900, round(base * _advance_purchase_multiplier(days)))


def _candidate_pairs(req: PlanRequest) -> list[tuple[str, str]]:
    o_city = find_city(req.origin.label)
    d_city = find_city(req.destination.label)
    if not o_city or not d_city:
        return []
    pairs = []
    for a in o_city.airports:
        for b in d_city.airports:
            if a != b and frozenset((a, b)) in DOMESTIC_ROUTES:
                pairs.append((a, b))
    return pairs[:2]


async def _surface_leg(origin: Place, dest: Place, req: PlanRequest, kind: LegKind, label: str) -> Leg:
    """Route one end of the trip with real DB data, falling back to a
    straight-line estimate only if the API is unavailable."""
    journeys = await fetch_journeys(origin, dest, req.depart_after, results=1)
    if journeys:
        it = journey_to_itinerary(journeys[0])
        if it:
            return Leg(kind, label, round(it.door_to_door_minutes, 1))
    km = haversine_km(origin.lat, origin.lon, dest.lat, dest.lon)
    return Leg(kind, f"{label} (estimated)", round(18 + km * 1.6, 1))


class AirProvider:
    name = "air-modelled"

    async def search(self, req: PlanRequest) -> ProviderResult:
        out: list[Itinerary] = []
        try:
            for dep_iata, arr_iata in _candidate_pairs(req):
                dep, arr = AIRPORTS[dep_iata], AIRPORTS[arr_iata]
                dep_place = Place(dep.station_query, dep.lat, dep.lon,
                                  station_id=await resolve_station(dep.station_query))
                arr_place = Place(arr.station_query, arr.lat, arr.lon,
                                  station_id=await resolve_station(arr.station_query))

                access = await _surface_leg(req.origin, dep_place, req, LegKind.ACCESS,
                                            f"Get to {dep_iata}")
                egress = await _surface_leg(arr_place, req.destination, req, LegKind.EGRESS,
                                            f"{arr_iata} into town")

                km = haversine_km(dep.lat, dep.lon, arr.lat, arr.lon)
                block = _block_minutes(km)
                checkin = CHECKIN_MIN_CHECKED if req.checked_bag else CHECKIN_MIN_CARRYON
                off = DISEMBARK_MIN_CHECKED if req.checked_bag else DISEMBARK_MIN_CARRYON

                legs = (
                    access,
                    Leg(LegKind.CHECKIN, "Check-in, security, boarding", checkin, productive=False),
                    Leg(LegKind.RIDE, f"{dep_iata} to {arr_iata}", round(block, 1),
                        line=f"{dep_iata}-{arr_iata}", productive=False),
                    Leg(LegKind.DISEMBARK, "Deplane and bags" if req.checked_bag else "Deplane",
                        off),
                    egress,
                )
                total_min = sum(leg.minutes for leg in legs)

                cost = [CostLine("Modelled airfare", _fare_cents(km, req.days_ahead))]
                if req.checked_bag:
                    cost.append(CostLine("Checked bag", CHECKED_BAG_CENTS))
                if not req.has_deutschlandticket:
                    cost.append(CostLine("Airport transfers, both ends", 2400))
                else:
                    cost.append(CostLine("Airport transfers (Deutschlandticket)", 0))

                notes = [
                    ("ESTIMATED fare — modelled from distance and how far ahead "
                     "you are booking, not a quote. Check before deciding."),
                    ("Times include getting to the airport, security and the "
                     "ride into town, which booking sites do not show."),
                ]
                if not dep.has_rail or not arr.has_rail:
                    notes.append("One airport has no direct rail link; allow extra slack.")

                out.append(
                    Itinerary(
                        mode=Mode.AIR,
                        provider="air-modelled",
                        depart=req.depart_after,
                        arrive=req.depart_after + timedelta(minutes=total_min),
                        legs=legs,
                        cost_lines=tuple(cost),
                        co2_g=round(km * CO2_G_PER_PKM["air_domestic"] + AIR_FIXED_G),
                        transfers=0,
                        confidence=Confidence.MODELLED,
                        deeplink=(
                            "https://www.google.com/travel/flights?q="
                            f"Flights%20{dep_iata}%20to%20{arr_iata}%20on%20"
                            f"{req.depart_after.date().isoformat()}"
                        ),
                        notes=tuple(notes),
                    )
                )
        except Exception as exc:
            log.exception("air provider failed")
            return ProviderResult(tuple(out), degraded=True,
                                  reason=f"Flight lookup failed: {exc}")
        return ProviderResult(tuple(out))
