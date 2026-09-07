"""Long-distance coach adapter.

FlixBus is effectively the whole German intercity coach market and has no
open API. There are two legitimate routes to live data: their affiliate or
distribution partner programme, or a reseller such as Omio or Distribusion.
Until you have one of those, this adapter models the journey from road
distance and marks it MODELLED, which is honest and good enough to rank.

`ENABLE_FLIX=true` switches on the HTTP path. Leave it off unless you have a
partner agreement — the endpoint is not public, and scraping it will get your
IP blocked long before it gets you a product.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from ..config import settings
from ..domain import (
    Confidence,
    CostLine,
    Itinerary,
    Leg,
    LegKind,
    Mode,
    PlanRequest,
    ProviderResult,
)
from ..geo import CO2_G_PER_PKM, haversine_km

log = logging.getLogger(__name__)

ROAD_DETOUR = 1.30       # autobahn routing vs straight line
AVG_SPEED_KMH = 68.0     # including scheduled stops, excluding traffic
STOP_MINUTES_PER_450KM = 25
ACCESS_MINUTES = 22      # coach stops sit at the edge of town, not the Hbf
MIN_FARE_CENTS = 1099


def _fare_cents(road_km: float, days: int) -> int:
    curve = [(30, 1.00), (14, 1.06), (7, 1.18), (3, 1.34), (0, 1.55)]
    mult = curve[-1][1]
    for d, m in curve:
        if days >= d:
            mult = m
            break
    return max(MIN_FARE_CENTS, round(road_km * 4.3 * mult))


class CoachProvider:
    name = "coach-modelled"

    async def search(self, req: PlanRequest) -> ProviderResult:
        try:
            direct_km = haversine_km(
                req.origin.lat, req.origin.lon, req.destination.lat, req.destination.lon
            )
            if direct_km < 70:
                return ProviderResult(())  # no coach market this short

            road_km = direct_km * ROAD_DETOUR
            ride = road_km / AVG_SPEED_KMH * 60 + (road_km / 450) * STOP_MINUTES_PER_450KM
            transfers = 0 if direct_km < 550 else 1

            legs = [
                Leg(LegKind.ACCESS, "Get to the coach stop", ACCESS_MINUTES),
                # Deliberately not productive. A tray table and patchy wifi for
                # ten hours is not a working environment, and pretending
                # otherwise would let the coach win every laptop-weighted search.
                Leg(LegKind.RIDE, "On the coach", round(ride, 1), line="FlixBus", productive=False),
            ]
            if transfers:
                legs.insert(2, Leg(LegKind.TRANSFER, "Change coaches", 35.0))
            legs.append(Leg(LegKind.EGRESS, "Coach stop into town", ACCESS_MINUTES))

            total = sum(leg.minutes for leg in legs)
            notes = ["Fare and timing are modelled from road distance."]
            if total > 600:
                notes.append("Ten hours plus — budget a recovery day at the far end.")

            return ProviderResult((
                Itinerary(
                    mode=Mode.COACH,
                    provider=self.name,
                    depart=req.depart_after,
                    arrive=req.depart_after + timedelta(minutes=total),
                    legs=tuple(legs),
                    cost_lines=(
                        CostLine("Modelled coach fare", _fare_cents(road_km, req.days_ahead)),
                        CostLine("Local transfers", 0 if req.has_deutschlandticket else 640),
                    ),
                    co2_g=round(road_km * CO2_G_PER_PKM["coach"]),
                    transfers=transfers,
                    confidence=Confidence.MODELLED,
                    deeplink="https://global.flixbus.com/",
                    notes=tuple(notes),
                ),
            ))
        except Exception as exc:
            log.exception("coach provider failed")
            return ProviderResult((), degraded=True, reason=f"Coach lookup failed: {exc}")


def build_coach_provider():
    if settings.enable_flix:
        log.warning("ENABLE_FLIX is set but no partner client is configured; using the model")
    return CoachProvider()
