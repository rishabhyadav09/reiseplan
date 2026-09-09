"""MOTIS / Transitous adapter.

Replaces the Deutsche Bahn adapter, which stopped working when DB began
answering with OPS_BLOCKED — a server-side block that no client can work
around. db-vendo-client's own README now recommends this path.

What this buys us beyond staying alive:

  * ~40 countries instead of one. Germany stops being load-bearing.
  * Real coach schedules, because Flix publishes GTFS. The modelled coach
    provider becomes a fallback rather than the only answer.
  * Native NIGHT_RAIL and HIGHSPEED_RAIL modes, so sleeper detection stops
    being a line-name prefix guess.
  * Trams, metros and local buses in the same query, which is what makes
    door-to-door honest rather than station-to-station.

What it costs: DB's live fares. MOTIS routes on GTFS, and GTFS-Fares v2
coverage is thin. Rail fares become modelled like everything else, and the
"live fare" badge is only shown where fare data actually came back.

API: https://api.transitous.org — /api/v5/plan and /api/v1/geocode.
Transitous is community-run and has a usage policy. Cache aggressively and
set a real User-Agent; this is donated infrastructure.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

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
from ..fares import estimate as estimate_fare
from ..geo import CO2_G_PER_PKM, haversine_km
from .base import UpstreamUnavailable, http

log = logging.getLogger(__name__)

# MOTIS mode -> our mode. v5 renamed METRO to SUBURBAN; both are accepted so a
# server on an older release still parses.
LONG_DISTANCE_MODES = {"HIGHSPEED_RAIL", "LONG_DISTANCE", "RAIL"}
NIGHT_MODES = {"NIGHT_RAIL"}
REGIONAL_MODES = {"REGIONAL_FAST_RAIL", "REGIONAL_RAIL", "SUBURBAN", "METRO",
                  "SUBWAY", "TRAM", "FUNICULAR", "AERIAL_LIFT"}
COACH_MODES = {"COACH"}
BUS_MODES = {"BUS"}
AIR_MODES = {"AIRPLANE"}
STREET_MODES = {"WALK", "BIKE", "RENTAL", "CAR", "ODM", "RIDE_SHARING", "FLEX"}

# Which of our modes an itinerary is, given the modes present in its legs.
# Order matters: a journey with any long-distance leg is a rail journey even
# if it starts with a tram.
_MODE_PRIORITY = [
    (NIGHT_MODES, Mode.NIGHT_RAIL),
    (LONG_DISTANCE_MODES, Mode.RAIL),
    (AIR_MODES, Mode.AIR),
    (COACH_MODES, Mode.COACH),
    (REGIONAL_MODES, Mode.RAIL_REGIONAL),
    (BUS_MODES, Mode.RAIL_REGIONAL),
]

CO2_BY_MODE = {
    Mode.RAIL: CO2_G_PER_PKM["rail_long"],
    Mode.NIGHT_RAIL: CO2_G_PER_PKM["rail_long"],
    Mode.RAIL_REGIONAL: CO2_G_PER_PKM["rail_regional"],
    Mode.COACH: CO2_G_PER_PKM["coach"],
    Mode.AIR: CO2_G_PER_PKM["air_domestic"],
}


async def _get(path: str, params: dict) -> dict | list:
    url = f"{settings.motis_base.rstrip('/')}{path}"
    last = "unknown"
    for attempt in range(3):
        try:
            resp = await http().get(url, params=params)
        except httpx.HTTPError as exc:
            last = type(exc).__name__
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {resp.status_code}"
            log.warning("motis unavailable path=%s status=%s", path, resp.status_code)
            continue
        if resp.status_code >= 400:
            raise UpstreamUnavailable(f"Transitous returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise UpstreamUnavailable("Transitous returned a malformed response") from None
    raise UpstreamUnavailable(f"Transitous unreachable after 3 attempts ({last})")


async def geocode(text: str, limit: int = 8) -> list[dict]:
    """Autocomplete across every region Transitous has data for."""
    ck = key_for("motis-geo", {"q": text.lower().strip(), "n": limit})

    async def fetch():
        try:
            data = await _get("/api/v1/geocode", {"text": text, "language": "en"})
        except UpstreamUnavailable:
            return None
        if not isinstance(data, list):
            return []
        out = []
        for m in data[:limit]:
            if m.get("lat") is None or m.get("lon") is None:
                continue
            out.append({
                "id": m.get("id"),
                "name": m.get("name") or text,
                "kind": (m.get("type") or "PLACE").lower(),
                "lat": m["lat"],
                "lon": m["lon"],
            })
        return out

    return await cache.get_or_set(ck, settings.cache_ttl_locations, fetch) or []


def _place_param(p: Place) -> str:
    """MOTIS takes a stop id or a `lat,lon` pair. Coordinates give us the
    walking legs, which is the whole point of a door-to-door envelope."""
    return f"{p.lat},{p.lon}"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, AttributeError):
        return None


def _leg_km(raw: dict) -> float:
    """MOTIS only populates `distance` on non-transit legs, so every train leg
    reports zero. Fall back to great-circle between the leg endpoints, which
    understates a winding route but is vastly better than calling it zero and
    telling someone a 220 km ICE emits nothing."""
    dist = raw.get("distance")
    if isinstance(dist, (int, float)) and dist > 0:
        return dist / 1000.0
    frm, to = raw.get("from") or {}, raw.get("to") or {}
    try:
        return haversine_km(frm["lat"], frm["lon"], to["lat"], to["lon"])
    except (KeyError, TypeError):
        return 0.0


def _classify(leg_modes: set[str]) -> Mode:
    for modes, resolved in _MODE_PRIORITY:
        if leg_modes & modes:
            return resolved
    return Mode.RAIL_REGIONAL


def _fare_cents(itin: dict) -> tuple[int | None, bool]:
    """Read GTFS-Fares v2 data if the feed carries it. Most do not, so this
    returns None far more often than not — and we say so rather than invent."""
    total = 0
    found = False
    for transfer in itin.get("fareTransfers") or []:
        for products in transfer.get("effectiveFareLegProducts") or []:
            for product in products or []:
                amount = (product or {}).get("amount")
                if isinstance(amount, (int, float)):
                    total += round(amount * 100)
                    found = True
    return (total, True) if found and total > 0 else (None, False)


PLACEHOLDER_NAMES = {"START", "END", "", None}


def _place_name(place: dict | None, fallback: str) -> str:
    name = (place or {}).get("name")
    return fallback if name in PLACEHOLDER_NAMES else name


def _country_of(itin: dict) -> str:
    """Crude but adequate: bounding box of the German-speaking core versus
    neighbours. A country pack would carry this properly."""
    for raw in itin.get("legs") or []:
        frm = raw.get("from") or {}
        lat, lon = frm.get("lat"), frm.get("lon")
        if lat is None:
            continue
        if 47.2 <= lat <= 55.1 and 5.8 <= lon <= 15.1:
            return "DE"
        if 46.3 <= lat <= 49.1 and 9.5 <= lon <= 17.2:
            return "AT"
        if 45.8 <= lat <= 47.9 and 5.9 <= lon <= 10.5:
            return "CH"
        if 42.3 <= lat <= 51.1 and -4.9 <= lon <= 8.3:
            return "FR"
        if 48.5 <= lat <= 55.1 and 14.1 <= lon <= 24.2:
            return "PL"
    return "DE"


def itinerary_from_motis(
    itin: dict, *, deutschlandticket: bool = False,
    origin_label: str = "your origin", destination_label: str = "your destination",
    days_ahead: int = 30, bahncard: int = 0,
) -> Itinerary | None:
    raw_legs = itin.get("legs") or []
    if not raw_legs:
        return None

    start = _parse_ts(itin.get("startTime"))
    end = _parse_ts(itin.get("endTime"))
    if not start or not end:
        return None

    legs: list[Leg] = []
    modes_seen: set[str] = set()
    co2 = 0.0
    transit_km = 0.0
    prev_end: datetime | None = None

    for idx, raw in enumerate(raw_legs):
        dep, arr = _parse_ts(raw.get("startTime")), _parse_ts(raw.get("endTime"))
        if not dep or not arr:
            continue

        if prev_end and (gap := (dep - prev_end).total_seconds() / 60.0) > 1:
            legs.append(Leg(LegKind.TRANSFER, "Waiting to change", round(gap, 1)))
        prev_end = arr

        minutes = max(0.0, (arr - dep).total_seconds() / 60.0)
        mode = (raw.get("mode") or "").upper()
        is_last = idx == len(raw_legs) - 1
        dest = _place_name(raw.get("to"),
                           destination_label if is_last else "the next stop")

        if mode in STREET_MODES:
            kind = (LegKind.ACCESS if idx == 0
                    else LegKind.EGRESS if is_last
                    else LegKind.TRANSFER)
            verb = "Walk" if mode == "WALK" else mode.replace("_", " ").title()
            legs.append(Leg(kind, f"{verb} to {dest}", round(minutes, 1)))
            continue

        modes_seen.add(mode)
        # displayName is "ICE 42"; routeShortName is a bare "42". MOTIS v4
        # added displayName for exactly this reason, so it must come first or
        # every German train renders as a meaningless number.
        name = (raw.get("displayName") or raw.get("routeShortName")
                or raw.get("headsign") or mode.replace("_", " ").title())
        km = _leg_km(raw)

        per_km = (CO2_G_PER_PKM["rail_long"] if mode in LONG_DISTANCE_MODES | NIGHT_MODES
                  else CO2_G_PER_PKM["air_domestic"] if mode in AIR_MODES
                  else CO2_G_PER_PKM["coach"] if mode in COACH_MODES | BUS_MODES
                  else CO2_G_PER_PKM["rail_regional"])
        co2 += km * per_km
        transit_km += km

        legs.append(Leg(
            kind=LegKind.RIDE,
            label=f"{name} to {dest}",
            minutes=round(minutes, 1),
            line=str(name),
            # A seat on a long-distance train is working time. Six minutes on
            # a tram is not, and neither is a coach.
            productive=(mode in LONG_DISTANCE_MODES
                        or (mode in REGIONAL_MODES and minutes >= 25)),
        ))

    if not legs:
        return None

    mode = _classify(modes_seen)
    fare, real_fare = _fare_cents(itin)

    notes: list[str] = []
    cost_lines: list[CostLine] = []
    confidence = Confidence.SCHEDULE

    if deutschlandticket and mode is Mode.RAIL_REGIONAL:
        cost_lines.append(CostLine("Covered by your Deutschlandticket", 0))
        notes.append("Marginal cost is zero — you already paid for the month.")
        confidence = Confidence.LIVE
    elif real_fare and fare:
        cost_lines.append(CostLine("Fare from the operator's feed", fare))
        confidence = Confidence.LIVE
    else:
        # No published fare. Estimate a band from the national tariff rather
        # than showing EUR 0.00, which reads as free and is useless for ranking.
        band = estimate_fare(
            km=transit_km, country=_country_of(itin), days_ahead=days_ahead,
            long_distance=mode in (Mode.RAIL, Mode.NIGHT_RAIL),
            bahncard=bahncard,
        )
        if band is None:
            cost_lines.append(CostLine("Fare not published in this feed", 0))
            notes.append("No fare data for this operator — check before booking.")
        else:
            cost_lines.append(
                CostLine(f"Estimated fare ({band.label()})", band.typical_cents))
            notes.append(
                f"Estimated from the {band.basis}, not a live quote. "
                f"Expect {band.label()}."
            )

    if mode is Mode.NIGHT_RAIL:
        cost_lines.append(CostLine("Hotel night saved", -9500))
        notes.append("Sleeper — the hotel saving is an assumption you can change.")

    return Itinerary(
        mode=mode,
        provider="transitous",
        depart=start,
        arrive=end,
        legs=tuple(legs),
        cost_lines=tuple(cost_lines),
        co2_g=round(co2),
        transfers=int(itin.get("transfers") or 0),
        confidence=confidence,
        deeplink=None,
        notes=tuple(notes),
    )


async def fetch_plan(
    origin: Place,
    destination: Place,
    when: datetime,
    *,
    arrive_by: bool = False,
    results: int = 5,
    regional_only: bool = False,
    via: Place | None = None,
) -> list[dict]:
    params: dict = {
        "fromPlace": _place_param(origin),
        "toPlace": _place_param(destination),
        "time": when.isoformat(),
        "arriveBy": "true" if arrive_by else "false",
        "numItineraries": results,
        "timetableView": "false",
        "detailedTransfers": "false",
    }
    if via is not None:
        params["via"] = _place_param(via)
        params["viaMinimumStay"] = 0      # a routing waypoint, not a stopover
    if regional_only:
        params["transitModes"] = "REGIONAL_RAIL,REGIONAL_FAST_RAIL,SUBURBAN,TRAM,SUBWAY,BUS"

    ck = key_for("motis-plan", params)

    async def fetch():
        data = await _get("/api/v5/plan", params)
        if isinstance(data, dict):
            return data.get("itineraries") or []
        return []

    return await cache.get_or_set(ck, settings.cache_ttl_journeys, fetch) or []


class MotisProvider:
    name = "transitous"

    async def search(self, req: PlanRequest) -> ProviderResult:
        out: list[Itinerary] = []
        try:
            itins = await fetch_plan(
                req.origin, req.destination, req.depart_after,
                arrive_by=req.arrive_by, results=5, via=req.via,
            )
            for raw in itins:
                it = itinerary_from_motis(
                    raw, origin_label=req.origin.label,
                    destination_label=req.destination.label,
                    days_ahead=req.days_ahead, bahncard=req.has_bahncard)
                if it:
                    out.append(it)

            if req.has_deutschlandticket:
                regional = await fetch_plan(
                    req.origin, req.destination, req.depart_after,
                    arrive_by=req.arrive_by, results=2, regional_only=True,
                )
                for raw in regional:
                    it = itinerary_from_motis(
                        raw, deutschlandticket=True,
                        origin_label=req.origin.label,
                        destination_label=req.destination.label,
                        days_ahead=req.days_ahead, bahncard=req.has_bahncard)
                    if it:
                        out.append(it)
        except UpstreamUnavailable as exc:
            log.warning("transitous unavailable: %s", exc)
            return ProviderResult((), degraded=True, reason=str(exc))
        except Exception as exc:
            log.exception("transitous provider failed")
            return ProviderResult((), degraded=True, reason=f"Routing failed: {exc}")
        return ProviderResult(tuple(out))
