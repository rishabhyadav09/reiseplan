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
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

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


def slug(name: str) -> str:
    """Retailer URL slug: lowercase, ASCII, hyphens.

    'Frankfurt am Main' -> 'frankfurt-am-main'
    'München'           -> 'muenchen'

    This is what the 404s were. Percent-encoding a city name produces
    'Frankfurt%20am%20Main', which every slug-based router rejects.
    """
    folded = (name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                  .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
                  .replace("ß", "ss"))
    ascii_only = (unicodedata.normalize("NFKD", folded)
                  .encode("ascii", "ignore").decode())
    # Drop bracketed qualifiers like "Frankfurt(Main)Hbf" -> "frankfurt hbf"
    ascii_only = re.sub(r"\([^)]*\)", " ", ascii_only)
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")


def rail_links(origin: str, destination: str, when: datetime) -> list[BookingLink]:
    o_slug, d_slug = slug(origin), slug(destination)
    return [
        BookingLink(
            "Check price on Trainline",
            _affiliate(
                f"https://www.thetrainline.com/train-times/{o_slug}-to-{d_slug}",
                "TRAINLINE_AFFILIATE_ID",
            ),
            "Covers most European operators in one checkout",
        ),
        BookingLink(
            "Book direct with DB",
            # int.bahn.de is DB's international search entry point and takes
            # plain station names as query params. Deep links into their
            # booking flow break on every redesign; this one degrades to a
            # usable search page instead of a 404.
            "https://int.bahn.de/en/buchung/fahrplan/suche?"
            + urlencode({"so": origin, "zo": destination, "hd": f"{_date(when)}T08:00:00"}),
            "Cheapest for German routes — no booking fee",
        ),
    ]


def coach_links(origin: str, destination: str, when: datetime) -> list[BookingLink]:
    # FlixBus's booking flow is keyed on internal city UUIDs and their public
    # URL format is undocumented and unstable. Rather than ship a guess that
    # 404s, the primary link is their route-slug page, which is a real page
    # and carries the route. Swap in a proper deep link once you have their
    # affiliate feed, which supplies the IDs.
    return [
        BookingLink(
            "Check price on FlixBus",
            _affiliate(
                f"https://global.flixbus.com/bus/{slug(origin)}-{slug(destination)}",
                "FLIX_AFFILIATE_ID",
            ),
            "Runs almost every intercity coach route in Germany",
        ),
    ]


def air_links(origin: str, destination: str, when: datetime) -> list[BookingLink]:
    return [
        BookingLink(
            "Compare flights",
            "https://www.google.com/travel/flights?"
            + urlencode({"q": f"Flights from {origin} to {destination} on {_date(when)}"}),
            "Prices here are modelled — check a real one before deciding",
        ),
    ]


def always_links(origin: str, destination: str) -> list[BookingLink]:
    return [
        BookingLink(
            "See every option on Rome2Rio",
            f"https://www.rome2rio.com/map/{slug(origin)}/{slug(destination)}",
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
