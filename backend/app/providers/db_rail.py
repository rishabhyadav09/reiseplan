"""Deutsche Bahn adapter.

This is the one provider with real fares and real schedules, and it does more
work than just "find me a train". Because the DB API accepts raw coordinates
as an origin or destination, it will happily route from someone's actual front
door and include the walking and local-transit legs. That is what produces a
genuine door-to-door envelope instead of a station-to-station one, and it is
also how we price the access leg to an airport for the flight comparison.

Upstream shape is FPTF (hafas-client v6), served by db-vendo-client.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..cache import cache, key_for
from ..config import settings
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
from ..geo import CO2_G_PER_PKM, haversine_km
from .base import UpstreamUnavailable, db_get

log = logging.getLogger(__name__)

LONG_DISTANCE = {"nationalExpress", "national"}
REGIONAL = {"regionalExpress", "regional", "suburban"}
NIGHT_LINES = ("NJ", "EN", "NJX")


def _endpoint_params(prefix: str, place: Place) -> dict:
    """DB accepts either a station id or a lat/lon pair. Prefer coordinates,
    because that is what makes the walking legs appear."""
    if place.station_id:
        return {prefix: place.station_id}
    return {
        f"{prefix}.latitude": place.lat,
        f"{prefix}.longitude": place.lon,
        f"{prefix}.address": place.label,
    }


async def resolve_station(query: str) -> str | None:
    """Look up an EVA number once, then cache it for a month."""
    ck = key_for("loc", {"q": query})

    async def fetch():
        try:
            data = await db_get("/locations", {"query": query, "results": 1,
                                               "poi": "false", "addresses": "false"})
        except UpstreamUnavailable:
            return None
        if isinstance(data, list) and data:
            return data[0].get("id")
        return None

    return await cache.get_or_set(ck, settings.cache_ttl_locations, fetch)


async def search_locations(query: str, limit: int = 8) -> list[dict]:
    """Typeahead over DB's own index: stations, addresses, airports, POIs.

    This is what replaces the hardcoded city list. DB indexes every stop in
    Germany plus a good deal of neighbouring Europe, so the catalogue stops
    being a file we maintain and starts being upstream's problem.
    """
    ck = key_for("locsearch", {"q": query.lower().strip(), "n": limit})

    async def fetch():
        try:
            data = await db_get("/locations", {
                "query": query, "results": limit,
                "stops": "true", "addresses": "true", "poi": "true",
            })
        except UpstreamUnavailable:
            return None
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            loc = item.get("location") or item
            lat, lon = loc.get("latitude"), loc.get("longitude")
            if lat is None or lon is None:
                continue
            out.append({
                "id": item.get("id"),
                "name": item.get("name") or item.get("address") or query,
                "kind": item.get("type") or "stop",
                "lat": lat,
                "lon": lon,
            })
        return out

    return await cache.get_or_set(ck, settings.cache_ttl_locations, fetch) or []


async def fetch_journeys(
    origin: Place,
    destination: Place,
    depart_after: datetime,
    *,
    results: int = 4,
    regional_only: bool = False,
    bahncard: int = 0,
    arrive_before: datetime | None = None,
    via: str | None = None,
    polyline: bool = False,
) -> list[dict]:
    params: dict = {
        **_endpoint_params("from", origin),
        **_endpoint_params("to", destination),
        "departure": depart_after.isoformat(),
        "results": results,
        "stopovers": "false",
        "remarks": "false",
        "tickets": "true",
        "language": "en",
    }
    if arrive_before is not None:
        # DB takes either departure or arrival, never both.
        params.pop("departure", None)
        params["arrival"] = arrive_before.isoformat()
    if via:
        params["via"] = via
    if polyline:
        params["polylines"] = "true"
    if regional_only:
        # Deutschlandticket routing: everything except long distance.
        params |= {"nationalExpress": "false", "national": "false"}
    if bahncard in (25, 50):
        params["loyaltyCard"] = f"BAHNCARD{bahncard}"

    ck = key_for("journeys", params)

    async def fetch():
        data = await db_get("/journeys", params)   # may raise UpstreamUnavailable
        if isinstance(data, dict):
            return data.get("journeys") or []
        return []

    out = await cache.get_or_set(ck, settings.cache_ttl_journeys, fetch)
    return out or []


def _leg_km(leg: dict) -> float:
    if leg.get("distance"):
        return float(leg["distance"]) / 1000.0
    o, d = leg.get("origin") or {}, leg.get("destination") or {}
    ol, dl = o.get("location") or o, d.get("location") or d
    try:
        return haversine_km(ol["latitude"], ol["longitude"], dl["latitude"], dl["longitude"])
    except (KeyError, TypeError):
        return 0.0


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def journey_to_itinerary(journey: dict, *, deutschlandticket: bool = False) -> Itinerary | None:
    raw_legs = journey.get("legs") or []
    if not raw_legs:
        return None

    depart = _parse_ts(raw_legs[0].get("departure") or raw_legs[0].get("plannedDeparture"))
    arrive = _parse_ts(raw_legs[-1].get("arrival") or raw_legs[-1].get("plannedArrival"))
    if not depart or not arrive:
        return None

    legs: list[Leg] = []
    transfers = 0
    co2 = 0.0
    is_night = False
    has_long_distance = False
    prev_end: datetime | None = None

    for idx, raw in enumerate(raw_legs):
        leg_dep = _parse_ts(raw.get("departure") or raw.get("plannedDeparture"))
        leg_arr = _parse_ts(raw.get("arrival") or raw.get("plannedArrival"))
        if not leg_dep or not leg_arr:
            continue

        # Waiting between vehicles is real time and belongs in the envelope.
        if prev_end and (gap := (leg_dep - prev_end).total_seconds() / 60.0) > 1:
            legs.append(Leg(LegKind.TRANSFER, "Waiting to change", round(gap, 1), productive=False))
        prev_end = leg_arr

        minutes = max(0.0, (leg_arr - leg_dep).total_seconds() / 60.0)
        dest_name = ((raw.get("destination") or {}).get("name")) or "next stop"

        if raw.get("walking"):
            first_or_last = idx == 0 or idx == len(raw_legs) - 1
            kind = LegKind.ACCESS if idx == 0 else LegKind.EGRESS if idx == len(raw_legs) - 1 else LegKind.TRANSFER
            label = "Walk to the platform" if not first_or_last else f"Walk to {dest_name}"
            legs.append(Leg(kind, label, round(minutes, 1)))
            continue

        line = raw.get("line") or {}
        product = line.get("product") or ""
        name = line.get("name") or product or "service"
        if product in LONG_DISTANCE:
            has_long_distance = True
        if any(str(name).upper().startswith(p) for p in NIGHT_LINES):
            is_night = True

        transfers += 1
        km = _leg_km(raw)
        factor = CO2_G_PER_PKM["rail_long" if product in LONG_DISTANCE else "rail_regional"]
        co2 += km * factor

        legs.append(
            Leg(
                kind=LegKind.RIDE,
                label=f"{name} to {dest_name}",
                minutes=round(minutes, 1),
                line=str(name),
                # A seat with a table and power is real working time; a packed
                # S-Bahn for six minutes is not.
                productive=product in LONG_DISTANCE or (product in REGIONAL and minutes >= 25),
            )
        )

    transfers = max(0, transfers - 1)

    notes: list[str] = []
    cost_lines: list[CostLine] = []
    confidence = Confidence.SCHEDULE

    if deutschlandticket:
        cost_lines.append(CostLine("Covered by your Deutschlandticket", 0))
        notes.append("Marginal cost is zero — you already paid for the month.")
        confidence = Confidence.LIVE
    else:
        price = journey.get("price") or {}
        amount = price.get("amount")
        if isinstance(amount, (int, float)) and amount > 0:
            cost_lines.append(CostLine("DB fare", round(amount * 100)))
            confidence = Confidence.LIVE
        else:
            # DB withholds a price when the journey needs a reservation it
            # cannot quote. Say so rather than inventing a number.
            cost_lines.append(CostLine("Fare not quoted by DB", 0))
            notes.append("DB returned no fare for this connection — check on bahn.de.")

    if is_night:
        mode = Mode.NIGHT_RAIL
        cost_lines.append(CostLine("Hotel night saved", -9500))
        notes.append("Sleeper — the hotel saving is an assumption you can change.")
    elif deutschlandticket or not has_long_distance:
        mode = Mode.RAIL_REGIONAL
    else:
        mode = Mode.RAIL

    return Itinerary(
        mode=mode,
        provider="deutsche-bahn",
        depart=depart,
        arrive=arrive,
        legs=tuple(legs),
        cost_lines=tuple(cost_lines),
        co2_g=round(co2),
        transfers=transfers,
        confidence=confidence,
        deeplink="https://www.bahn.de/buchung/fahrplan/suche",
        notes=tuple(notes),
    )


class DBRailProvider:
    name = "deutsche-bahn"

    async def search(self, req: PlanRequest) -> ProviderResult:
        out: list[Itinerary] = []
        try:
            journeys = await fetch_journeys(
                req.origin, req.destination, req.depart_after, bahncard=req.has_bahncard
            )
            for j in journeys:
                it = journey_to_itinerary(j)
                if it:
                    out.append(it)

            if req.has_deutschlandticket:
                regional = await fetch_journeys(
                    req.origin, req.destination, req.depart_after,
                    results=2, regional_only=True,
                )
                for j in regional:
                    it = journey_to_itinerary(j, deutschlandticket=True)
                    if it:
                        out.append(it)
        except UpstreamUnavailable as exc:
            log.warning("db unavailable: %s", exc)
            return ProviderResult((), degraded=True, reason=str(exc))
        except Exception as exc:
            log.exception("db provider failed")
            return ProviderResult((), degraded=True, reason=f"Rail lookup failed: {exc}")
        return ProviderResult(tuple(out))
