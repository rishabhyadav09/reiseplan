from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import anywhere as anywhere_mod
from . import auth, feedback
from .cache import cache
from .catalog import CITIES, find_city
from .domain import Confidence, Place, PlanRequest
from .planner import plan, weights_from
from .providers.base import close_http
from .providers.db_rail import resolve_station, search_locations
from .providers.motis import geocode
from .scoring import PRESETS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
BERLIN = timezone(timedelta(hours=2))


BUILD = os.getenv("BUILD_SHA", "dev")


@asynccontextmanager
async def lifespan(_: FastAPI):
    auth.warn_if_open()
    feedback.init()
    yield
    await close_http()
    await cache.close()


app = FastAPI(title="Reiseplan", version="0.1.0", lifespan=lifespan)
_origins = [o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class LegOut(BaseModel):
    kind: str
    label: str
    minutes: float
    line: str | None = None
    productive: bool


class OptionOut(BaseModel):
    mode: str
    provider: str
    confidence: str
    match: int
    depart: datetime
    arrive: datetime
    door_to_door_minutes: float
    total_cents: int
    productive_minutes: float
    co2_g: int
    transfers: int
    legs: list[LegOut]
    cost_lines: list[dict]
    generalized_cents: int
    breakdown: dict[str, int]
    notes: list[str]
    deeplink: str | None


class PlanOut(BaseModel):
    origin: str
    destination: str
    depart_after: datetime
    preset: str
    degraded: bool = False
    options: list[OptionOut]
    warnings: list[str] = Field(default_factory=list)


async def _resolve(text: str, station_id: str | None = None,
                   lat: float | None = None, lon: float | None = None) -> Place:
    """Prefer an explicit id or coordinates from the typeahead. Fall back to
    the catalogue, then to a live location search, before giving up."""
    if station_id and lat is not None and lon is not None:
        return Place(label=text, lat=lat, lon=lon, station_id=station_id)

    city = find_city(text)
    if city is not None:
        return Place(city.name, city.lat, city.lon,
                     station_id=await resolve_station(city.station_query))

    hits = await geocode(text, limit=1) or await search_locations(text, limit=1)
    if hits:
        h = hits[0]
        return Place(h["name"], h["lat"], h["lon"], station_id=h.get("id"))

    raise HTTPException(404, f"Could not find a place called '{text}'")


@app.get("/healthz")
async def healthz() -> dict:
    """Unauthenticated on purpose — deploy health checks run before login."""
    return {"ok": True, "build": BUILD, "gated": auth.enabled()}


class LoginIn(BaseModel):
    code: str


@app.post("/api/login")
async def login(body: LoginIn, response: Response) -> dict:
    if not auth.enabled():
        return {"tester": "open-access", "gated": False}
    minted = auth.mint(body.code)
    if minted is None:
        raise HTTPException(401, "That code is not valid for this round.")
    tester, token = minted
    response.set_cookie(
        auth.COOKIE, token, max_age=auth.MAX_AGE_S,
        httponly=True, samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
    )
    return {"tester": tester, "gated": True}


@app.get("/api/me")
async def me(tester: str = Depends(auth.current_tester)) -> dict:
    return {"tester": tester, "build": BUILD}


class FeedbackIn(BaseModel):
    verdict: str = Field(pattern="^(right|wrong|unsure)$")
    comment: str | None = None
    query: dict
    ranking: list[dict] = Field(default_factory=list)


@app.post("/api/feedback")
async def post_feedback(
    body: FeedbackIn, tester: str = Depends(auth.current_tester)
) -> dict:
    row_id = feedback.record(
        tester=tester, verdict=body.verdict, comment=body.comment,
        query=body.query, ranking=body.ranking, build=BUILD,
    )
    return {"id": row_id, "thanks": True}


@app.get("/api/feedback/summary")
async def feedback_summary(tester: str = Depends(auth.current_tester)) -> dict:
    return feedback.summary()


@app.get("/api/feedback/export.csv")
async def feedback_csv(tester: str = Depends(auth.current_tester)) -> PlainTextResponse:
    import csv
    import io

    rows = feedback.export_rows()
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=["id", "created_at", "tester", "verdict", "comment", "query", "build"],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    return PlainTextResponse(
        buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=uat-feedback.csv"},
    )


@app.get("/api/locations")
async def locations(
    q: str = Query(..., min_length=2, max_length=80),
    tester: str = Depends(auth.current_tester),
) -> list[dict]:
    """Typeahead. Falls back to the built-in catalogue if DB is unreachable,
    so the box still works during an outage."""
    hits = await geocode(q)          # global coverage
    if not hits:
        hits = await search_locations(q)   # DB fallback, if it is answering
    if hits:
        return hits
    needle = q.strip().lower()
    return [
        {"id": None, "name": c.name, "kind": "city", "lat": c.lat, "lon": c.lon}
        for c in CITIES.values()
        if needle in c.name.lower()
    ][:8]


@app.get("/api/anywhere")
async def anywhere(
    origin: str = Query(..., min_length=2),
    origin_lat: float | None = None,
    origin_lon: float | None = None,
    days_ahead: int = Query(21, ge=0, le=365),
    max_fare: int | None = Query(None, ge=0, description="euros"),
    max_hours: float | None = Query(None, gt=0, le=48),
    bahncard: int = Query(0, ge=0, le=50),
    limit: int = Query(40, ge=1, le=100),
    depart_at: datetime | None = None,
    tester: str = Depends(auth.current_tester),
) -> dict:
    """One origin, everywhere worth going. Estimates only — no upstream calls,
    which is exactly why it can price hundreds of destinations at once."""
    place = await _resolve(origin, None, origin_lat, origin_lon)
    country = "DE"
    for d in anywhere_mod.DESTINATIONS:
        if abs(d.lat - place.lat) < 1.2 and abs(d.lon - place.lon) < 1.6:
            country = d.country
            break

    results = anywhere_mod.search(
        origin_lat=place.lat, origin_lon=place.lon, origin_country=country,
        days_ahead=days_ahead,
        max_fare_cents=max_fare * 100 if max_fare is not None else None,
        max_hours=max_hours,
        bahncard=bahncard if bahncard in (25, 50) else 0,
        limit=limit,
        depart_at=(depart_at.replace(tzinfo=BERLIN) if depart_at
                   and depart_at.tzinfo is None else depart_at),
    )
    return {
        "origin": place.label,
        "count": len(results),
        "disclaimer": ("Estimated from distance and published tariffs, not live "
                       "quotes. Tap a destination for a real routing."),
        "destinations": [
            {
                "name": o.destination.name, "country": o.destination.country,
                "blurb": o.destination.blurb,
                "lat": o.destination.lat, "lon": o.destination.lon,
                "km": round(o.km), "mode": o.mode,
                "hours": round(o.hours, 1),
                "fare_label": o.fare_label,
                "fare_low_cents": o.fare_low_cents,
                "fare_typical_cents": o.fare_typical_cents,
                "co2_kg": round(o.co2_kg),
                "note": o.note,
                "depart_at": o.depart_at,
                "arrive_at": o.arrive_at,
                "arrival_note": o.arrival_note(),
            }
            for o in results
        ],
    }


@app.get("/api/cities")
async def cities() -> list[dict]:
    return [
        {"key": c.key, "name": c.name, "airports": list(c.airports)}
        for c in sorted(CITIES.values(), key=lambda c: c.name)
    ]


@app.get("/api/plan", response_model=PlanOut)
async def plan_route(
    origin: str = Query(..., min_length=2),
    destination: str = Query(..., min_length=2),
    origin_id: str | None = None,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
    destination_id: str | None = None,
    destination_lat: float | None = None,
    destination_lon: float | None = None,
    depart: datetime | None = None,
    arrive_before: datetime | None = None,
    preset: str = Query("balanced"),
    vot_cents: int | None = Query(None, ge=0, le=50000),
    checked_bag: bool = False,
    deutschlandticket: bool = False,
    bahncard: int = Query(0, ge=0, le=50),
    tester: str = Depends(auth.current_tester),
) -> PlanOut:
    if preset not in PRESETS:
        raise HTTPException(400, f"preset must be one of {sorted(PRESETS)}")

    depart_after = arrive_before or depart or (datetime.now(BERLIN) + timedelta(hours=2))
    if depart_after.tzinfo is None:
        depart_after = depart_after.replace(tzinfo=BERLIN)

    req = PlanRequest(
        origin=await _resolve(origin, origin_id, origin_lat, origin_lon),
        destination=await _resolve(destination, destination_id,
                                   destination_lat, destination_lon),
        depart_after=depart_after,
        checked_bag=checked_bag,
        has_deutschlandticket=deutschlandticket,
        has_bahncard=bahncard if bahncard in (25, 50) else 0,
        arrive_by=arrive_before is not None,
    )

    scored, degraded = await plan(req, weights_from(preset, vot_cents))

    warnings: list[str] = list(degraded)
    if not scored:
        warnings.append("No options came back for this route.")
    elif degraded and not any(
        s_.itinerary.mode.value.startswith("rail") for s_ in scored
    ):
        # The case that produced a lone 4h20 coach for Dortmund-Frankfurt.
        warnings.insert(0, "Train options are missing because the rail lookup "
                           "failed — the results below are NOT a fair comparison.")
    if any(s.itinerary.confidence is Confidence.MODELLED for s in scored):
        warnings.append("Options marked 'modelled' use estimated fares, not live quotes.")

    return PlanOut(
        origin=req.origin.label,
        destination=req.destination.label,
        depart_after=depart_after,
        preset=preset,
        degraded=bool(degraded),
        warnings=warnings,
        options=[
            OptionOut(
                mode=s.itinerary.mode.value,
                provider=s.itinerary.provider,
                confidence=s.itinerary.confidence.value,
                match=s.match,
                depart=s.itinerary.depart,
                arrive=s.itinerary.arrive,
                door_to_door_minutes=round(s.itinerary.door_to_door_minutes, 1),
                total_cents=s.itinerary.total_cents,
                productive_minutes=round(s.itinerary.productive_minutes, 1),
                co2_g=s.itinerary.co2_g,
                transfers=s.itinerary.transfers,
                legs=[
                    LegOut(kind=l.kind.value, label=l.label, minutes=l.minutes,
                           line=l.line, productive=l.productive)
                    for l in s.itinerary.legs
                ],
                cost_lines=[{"label": c.label, "cents": c.cents} for c in s.itinerary.cost_lines],
                generalized_cents=s.generalized_cents,
                breakdown={
                    "fare": s.itinerary.total_cents,
                    "time": s.time_cents,
                    "productivity_credit": s.productivity_credit_cents,
                    "carbon": s.carbon_cents,
                    "hassle": s.hassle_cents,
                },
                notes=list(s.itinerary.notes),
                deeplink=s.itinerary.deeplink,
            )
            for s in scored
        ],
    )


_WEB = Path(__file__).resolve().parents[2] / "web"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_WEB / "index.html")


@app.get("/admin")
async def admin() -> FileResponse:
    """Feedback dashboard. Gated by the same tester cookie as everything else —
    good enough for a five-person round, not for anything wider."""
    return FileResponse(_WEB / "admin.html")
