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
