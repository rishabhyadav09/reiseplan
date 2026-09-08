"""Booking hand-off.

We never hold fares or take payment. Each result links out to a retailer with
the route and date pre-filled; they show the real price and handle the sale.
That is Rome2Rio's model, and for a small team it is the right one: no PCI
scope, no refunds, no settlement with thirty carriers, and nobody phoning you
when ÖBB cancels a sleeper.

Affiliate IDs are config, not code. Sign up with Trainline or Omio through an
affiliate network, set the env vars, and every existing link starts earning
without a deploy.

Deep-link formats are best-effort and drift when retailers redesign. Each one
degrades to that retailer's search page rather than a 404, which is why the
builders below never raise.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode

from .domain import Mode


@dataclass(frozen=True, slots=True)
class BookingLink:
    label: str          # what the button says
    url: str
    why: str            # why this retailer, shown as a hint


def _affiliate(url: str, network_key: str) -> str:
    """Wrap in an affiliate redirect when one is configured, else pass through."""
    tag = os.getenv(network_key)
    if not tag:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode({'affiliate': tag})}"


def _date(when: datetime) -> str:
    return when.date().isoformat()


def rail_links(origin: str, destination: str, when: datetime) -> list[BookingLink]:
    o, d = quote(origin), quote(destination)
    return [
        BookingLink(
            "Check price on Trainline",
            _affiliate(
                f"https://www.thetrainline.com/train-times/{o}-to-{d}"
                f"?outwardDate={_date(when)}",
                "TRAINLINE_AFFILIATE_ID",
            ),
            "Covers most European operators in one checkout",
        ),
        BookingLink(
            "Book direct with DB",
            "https://www.bahn.de/buchung/fahrplan/suche#sts=true"
            f"&so={o}&zo={d}&hd={_date(when)}T08:00:00",
            "Cheapest for German routes — no booking fee",
        ),
    ]


def coach_links(origin: str, destination: str, when: datetime) -> list[BookingLink]:
    return [
        BookingLink(
            "Check price on FlixBus",
            _affiliate("https://global.flixbus.com/", "FLIX_AFFILIATE_ID"),
            "Runs almost every intercity coach route in Germany",
        ),
    ]


def air_links(origin: str, destination: str, when: datetime) -> list[BookingLink]:
    return [
        BookingLink(
            "Compare flights",
            "https://www.google.com/travel/flights?q="
            + quote(f"Flights from {origin} to {destination} on {_date(when)}"),
            "Prices here are modelled — check a real one before deciding",
        ),
    ]


def always_links(origin: str, destination: str) -> list[BookingLink]:
    return [
        BookingLink(
            "See every option on Rome2Rio",
            f"https://www.rome2rio.com/map/{quote(origin)}/{quote(destination)}",
            "Useful sanity check against our ranking",
        ),
    ]


def for_itinerary(
    mode: Mode, origin: str, destination: str, when: datetime
) -> list[BookingLink]:
    """Retailers worth showing for this mode, best first."""
    by_mode = {
        Mode.RAIL: rail_links,
        Mode.NIGHT_RAIL: rail_links,
        Mode.RAIL_REGIONAL: rail_links,
        Mode.COACH: coach_links,
        Mode.AIR: air_links,
    }
    builder = by_mode.get(mode)
    links = builder(origin, destination, when) if builder else []
    return links + always_links(origin, destination)
