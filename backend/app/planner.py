from __future__ import annotations

import asyncio
import logging

from .domain import Itinerary, Mode, PlanRequest
from .providers.air import AirProvider
from .providers.coach import build_coach_provider
from .providers.db_rail import DBRailProvider
from .scoring import PRESETS, Scored, Weights, rank

log = logging.getLogger(__name__)

PROVIDERS = [DBRailProvider(), AirProvider(), build_coach_provider()]

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


async def plan(req: PlanRequest, weights: Weights) -> list[Scored]:
    results = await asyncio.gather(
        *(p.search(req) for p in PROVIDERS), return_exceptions=True
    )

    itineraries: list[Itinerary] = []
    for provider, result in zip(PROVIDERS, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("provider %s raised: %s", provider.name, result)
            continue
        itineraries.extend(result)

    if not itineraries:
        return []
    return _trim(rank(itineraries, weights, checked_bag=req.checked_bag))


def weights_from(preset: str, vot_cents: int | None) -> Weights:
    base = PRESETS.get(preset, PRESETS["balanced"])
    if vot_cents is None:
        return base
    return Weights(max(0, vot_cents), base.carbon_cents_per_kg, base.productivity)
