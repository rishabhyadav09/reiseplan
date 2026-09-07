from __future__ import annotations

import asyncio
import logging

from .config import settings
from .domain import Itinerary, Mode, PlanRequest
from .providers.air import AirProvider
from .providers.coach import build_coach_provider
from .providers.db_rail import DBRailProvider
from .scoring import PRESETS, Scored, Weights, rank

log = logging.getLogger(__name__)

def _providers():
    active = [DBRailProvider(), build_coach_provider()]
    if settings.enable_air:
        active.append(AirProvider())
    return active


PROVIDERS = _providers()

# How many of each mode to surface. Four near-identical ICEs is noise.
PER_MODE_LIMIT = {
    Mode.RAIL: 2,
    Mode.RAIL_REGIONAL: 1,
    Mode.NIGHT_RAIL: 1,
    Mode.AIR: 1,
    Mode.COACH: 1,
}


def _trim(scored: list[Scored]) -> list[Scored]:
    seen: dict[Mode, int] = {}
    out: list[Scored] = []
    for row in scored:
        mode = row.itinerary.mode
        count = seen.get(mode, 0)
        if count >= PER_MODE_LIMIT.get(mode, 1):
            continue
        seen[mode] = count + 1
        out.append(row)
    return out


async def plan(req: PlanRequest, weights: Weights) -> tuple[list[Scored], list[str]]:
    """Return the ranking and any degradation notices.

    The notices matter as much as the ranking. If rail is down, a coach at the
    top of the list is not an answer — it is the absence of one, and the caller
    has to be able to say so.
    """
    results = await asyncio.gather(
        *(p.search(req) for p in PROVIDERS), return_exceptions=True
    )

    itineraries: list[Itinerary] = []
    degraded: list[str] = []
    for provider, result in zip(PROVIDERS, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("provider %s raised: %s", provider.name, result)
            degraded.append(f"{provider.name} failed unexpectedly.")
            continue
        itineraries.extend(result.itineraries)
        if result.degraded and result.reason:
            degraded.append(result.reason)

    if not itineraries:
        return [], degraded
    return _trim(rank(itineraries, weights, checked_bag=req.checked_bag)), degraded


def weights_from(preset: str, vot_cents: int | None) -> Weights:
    base = PRESETS.get(preset, PRESETS["balanced"])
    if vot_cents is None:
        return base
    return Weights(max(0, vot_cents), base.carbon_cents_per_kg, base.productivity)
