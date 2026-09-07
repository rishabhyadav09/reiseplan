"""Normalised domain types.

Every provider adapter must return `Itinerary` objects. Nothing downstream of
this module knows whether an itinerary came from Deutsche Bahn, FlixBus or a
fare model, which is what lets the scorer treat all modes on equal terms.

Money is integer cents throughout. No floats touch a price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Mode(str, Enum):
    RAIL = "rail"
    RAIL_REGIONAL = "rail_regional"
    NIGHT_RAIL = "night_rail"
    COACH = "coach"
    AIR = "air"


class LegKind(str, Enum):
    ACCESS = "access"          # front door to the first boarding point
    RIDE = "ride"              # actually moving on a vehicle
    TRANSFER = "transfer"      # changing between vehicles
    CHECKIN = "checkin"        # airport arrival buffer, security, boarding
    DISEMBARK = "disembark"    # deplaning and baggage reclaim
    EGRESS = "egress"          # last boarding point to the destination door


class Confidence(str, Enum):
    LIVE = "live"              # real fare and schedule from an operator API
    SCHEDULE = "schedule"      # real schedule, modelled fare
    MODELLED = "modelled"      # both modelled


@dataclass(frozen=True, slots=True)
class Leg:
    kind: LegKind
    label: str
    minutes: float
    line: str | None = None
    productive: bool = False   # can you realistically open a laptop here


@dataclass(frozen=True, slots=True)
class CostLine:
    """One line on the true-cost bill. Negative cents are savings."""

    label: str
    cents: int


@dataclass(frozen=True, slots=True)
class Itinerary:
    mode: Mode
    provider: str
    depart: datetime
    arrive: datetime
    legs: tuple[Leg, ...]
    cost_lines: tuple[CostLine, ...]
    co2_g: int
    transfers: int
    confidence: Confidence
    deeplink: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def door_to_door_minutes(self) -> float:
        """The number the booking sites do not show you."""
        return sum(leg.minutes for leg in self.legs)

    @property
    def total_cents(self) -> int:
        return sum(line.cents for line in self.cost_lines)

    @property
    def productive_minutes(self) -> float:
        return sum(leg.minutes for leg in self.legs if leg.productive)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """What a provider returns, including whether it could answer at all.

    A provider that is DOWN and a provider that legitimately has no service on
    a route both return zero itineraries. Conflating those two is how a coach
    ends up presented as the best way from Dortmund to Frankfurt.
    """

    itineraries: tuple[Itinerary, ...]
    degraded: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Place:
    """Either a catalogue city or a free-form address the user typed."""

    label: str
    lat: float
    lon: float
    station_id: str | None = None   # DB EVA number when we know it
    iata: str | None = None


@dataclass(frozen=True, slots=True)
class PlanRequest:
    origin: Place
    destination: Place
    depart_after: datetime
    checked_bag: bool = False
    has_deutschlandticket: bool = False
    has_bahncard: int = 0            # 0, 25, 50
    arrive_by: bool = False
    passengers: int = 1

    @property
    def days_ahead(self) -> int:
        delta = self.depart_after - datetime.now(tz=self.depart_after.tzinfo)
        return max(0, delta.days)
