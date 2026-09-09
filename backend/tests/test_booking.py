"""Booking hand-off links."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest

from app.booking import for_itinerary
from app.domain import Mode

WHEN = datetime(2026, 10, 14, 8, 0, tzinfo=timezone(timedelta(hours=2)))


def links(mode):
    return for_itinerary(mode, "Dortmund", "Frankfurt am Main", WHEN)


@pytest.mark.parametrize("mode", list(Mode))
def test_every_mode_gets_at_least_one_working_link(mode):
    out = links(mode)
    assert out
    for link in out:
        parsed = urlparse(link.url)
        assert parsed.scheme == "https"
        assert parsed.netloc


@pytest.mark.parametrize("mode", list(Mode))
def test_every_link_explains_why_that_retailer(mode):
    """A row of unlabelled logos is not a choice. Each needs a reason."""
    for link in links(mode):
        assert link.why and len(link.why) > 10


def test_rail_offers_both_an_aggregator_and_the_operator_direct():
    labels = " ".join(link.label for link in links(Mode.RAIL))
    assert "Trainline" in labels
    assert "DB" in labels, "direct booking avoids the aggregator's fee"


def test_the_destination_is_encoded_not_broken_by_spaces():
    for link in links(Mode.RAIL):
        assert " " not in link.url


def test_the_travel_date_is_carried_into_rail_links():
    assert any("2026-10-14" in link.url for link in links(Mode.RAIL))


def test_flights_warn_that_our_price_is_modelled():
    why = " ".join(link.why for link in links(Mode.AIR))
    assert "modelled" in why.lower()


def test_every_mode_gets_the_independent_cross_check():
    for mode in Mode:
        assert any("rome2rio" in link.url for link in links(mode))


def test_affiliate_ids_are_applied_when_configured(monkeypatch):
    monkeypatch.setenv("TRAINLINE_AFFILIATE_ID", "reiseplan-123")
    trainline = next(link for link in links(Mode.RAIL) if "trainline" in link.url)
    assert "reiseplan-123" in trainline.url


def test_links_work_unchanged_without_any_affiliate_setup(monkeypatch):
    monkeypatch.delenv("TRAINLINE_AFFILIATE_ID", raising=False)
    trainline = next(link for link in links(Mode.RAIL) if "trainline" in link.url)
    assert "affiliate" not in trainline.url
    assert trainline.url.startswith("https://")


# --- the 404 regression -----------------------------------------------------
# Shape tests passed while every link was broken. These assert the properties
# that actually determine whether a URL resolves.

from app.booking import slug


@pytest.mark.parametrize("name,expected", [
    ("Frankfurt am Main", "frankfurt-am-main"),
    ("München", "muenchen"),
    ("Köln", "koeln"),
    ("Zürich", "zuerich"),
    ("Frankfurt(Main)Hbf", "frankfurt-hbf"),
    ("Sankt Pölten", "sankt-poelten"),
])
def test_city_names_become_retailer_slugs(name, expected):
    assert slug(name) == expected


def test_no_link_ever_contains_percent_encoded_spaces():
    """'Frankfurt%20am%20Main' in a path segment is what 404'd."""
    for mode in Mode:
        for link in for_itinerary(mode, "Frankfurt am Main", "München", WHEN):
            path = urlparse(link.url).path
            assert "%20" not in path, link.url
            assert "%C3" not in path, f"unescaped umlaut in path: {link.url}"
            assert "+" not in path, link.url


def test_slugs_carry_no_uppercase_or_punctuation():
    for mode in (Mode.RAIL, Mode.NIGHT_RAIL, Mode.RAIL_REGIONAL):
        for link in for_itinerary(mode, "Frankfurt(Main)Hbf", "Zürich HB", WHEN):
            path = urlparse(link.url).path
            assert path == path.lower(), link.url
            assert "(" not in path and ")" not in path


def test_trainline_uses_its_documented_slug_route():
    link = next(x for x in links(Mode.RAIL) if "thetrainline" in x.url)
    assert "/train-times/dortmund-to-frankfurt-am-main" in link.url


def test_db_puts_station_names_in_the_query_not_the_path():
    """Path segments must be slugs; query values may be encoded."""
    link = next(x for x in links(Mode.RAIL) if "bahn.de" in x.url)
    parsed = urlparse(link.url)
    assert parsed.path.count("/") >= 2
    assert "so=" in parsed.query and "zo=" in parsed.query


def test_every_link_is_a_bare_absolute_url_with_no_fragment_only_target():
    """A URL that is only a fragment cannot carry search state on first load."""
    for mode in Mode:
        for link in for_itinerary(mode, "Dortmund", "Berlin", WHEN):
            parsed = urlparse(link.url)
            assert parsed.netloc and parsed.scheme == "https"
            assert parsed.path not in ("", "/") or parsed.query, link.url


def test_awkward_names_do_not_produce_empty_slugs():
    for name in ("Praha", "Wien", "'s-Hertogenbosch", "Aix-en-Provence"):
        assert slug(name), name
