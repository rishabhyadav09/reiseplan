"""Static checks on the served HTML.

A missing element turned $('swap').addEventListener into a TypeError that
aborted the whole inline script, so the submit handler never bound and
"Compare routes" fell through to a native form POST — a page reload with no
results, and every other new control dead at the same time.

Nothing here needs a browser. These are the cheap checks that would have
caught it.
"""

import re
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text()
SCRIPT = "\n".join(re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", HTML, re.DOTALL))
IDS = set(re.findall(r'(?:^|\s)id="([^"]+)"', HTML))
REFERENCED = set(re.findall(r"\$\('([^']+)'\)", SCRIPT))


def test_every_element_the_script_touches_exists():
    missing = sorted(REFERENCED - IDS)
    assert not missing, f"$() references with no matching id: {missing}"


def test_no_duplicate_ids():
    ids = re.findall(r'(?:^|\s)id="([^"]+)"', HTML)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate ids: {dupes}"


@pytest.mark.parametrize("element", [
    "origin", "destination", "via", "swap", "depart", "timemode",
    "preset", "vot", "dticket", "bc50", "bag", "q", "out",
])
def test_required_controls_are_present(element):
    assert f'id="{element}"' in HTML


def test_the_search_form_prevents_its_own_default_submit():
    """Without this the browser does a native POST and reloads the page."""
    assert "$('q').addEventListener('submit'" in SCRIPT
    assert "e.preventDefault()" in SCRIPT


def test_both_place_fields_offer_a_clear_button():
    for field in ("origin", "destination", "via"):
        assert f'data-clear="{field}"' in HTML


def test_swap_is_wired_defensively():
    """Optional chaining, so a future markup change degrades instead of
    killing every handler registered after it."""
    assert "$('swap')?." in SCRIPT


def test_booking_links_are_rendered_for_each_result():
    assert "o.booking" in SCRIPT
    assert 'rel="noopener nofollow"' in SCRIPT


def test_the_advanced_controls_are_behind_a_disclosure():
    """Value-of-time must not sit on the front page of a travel app."""
    assert '<details class="more">' in HTML
    body_before_details = HTML.split('<details class="more">')[0]
    assert 'id="vot"' not in body_before_details


def test_the_page_is_served_uncacheable():
    """A tester on a cached page reports bugs fixed two deploys ago."""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "")
    assert r.headers.get("x-build")
