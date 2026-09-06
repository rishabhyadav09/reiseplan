"""Parser tests against a payload shaped like a real db-vendo-client response.

Recorded rather than mocked at the HTTP layer, because what breaks in
production is the parsing, not the request.
"""

from app.domain import Confidence, Mode
from app.providers.db_rail import journey_to_itinerary

DORTMUND_BERLIN = {
    "legs": [
        {
            "origin": {"type": "location", "latitude": 51.5136, "longitude": 7.4653,
                       "address": "Dortmund, Kampstraße 1"},
            "destination": {"type": "stop", "id": "8000080", "name": "Dortmund Hbf",
                            "location": {"latitude": 51.5177, "longitude": 7.4592}},
            "departure": "2026-10-14T08:02:00+02:00",
            "arrival": "2026-10-14T08:14:00+02:00",
            "walking": True,
            "distance": 900,
        },
        {
            "origin": {"type": "stop", "id": "8000080", "name": "Dortmund Hbf",
                       "location": {"latitude": 51.5177, "longitude": 7.4592}},
            "destination": {"type": "stop", "id": "8000152", "name": "Hannover Hbf",
                            "location": {"latitude": 52.3768, "longitude": 9.7411}},
            "departure": "2026-10-14T08:31:00+02:00",
            "arrival": "2026-10-14T10:15:00+02:00",
            "line": {"type": "line", "name": "ICE 946", "product": "nationalExpress",
                     "mode": "train"},
        },
        {
            "origin": {"type": "stop", "id": "8000152", "name": "Hannover Hbf",
                       "location": {"latitude": 52.3768, "longitude": 9.7411}},
            "destination": {"type": "stop", "id": "8011160", "name": "Berlin Hbf",
                            "location": {"latitude": 52.5250, "longitude": 13.3694}},
            "departure": "2026-10-14T10:30:00+02:00",
            "arrival": "2026-10-14T12:07:00+02:00",
            "line": {"type": "line", "name": "ICE 692", "product": "nationalExpress",
                     "mode": "train"},
        },
    ],
    "price": {"amount": 69.9, "currency": "EUR", "hint": None},
    "refreshToken": "T$A=1@O=Dortmund",
}


def test_parses_a_two_train_journey_end_to_end():
    it = journey_to_itinerary(DORTMUND_BERLIN)
    assert it is not None
    assert it.mode is Mode.RAIL
    assert it.confidence is Confidence.LIVE
    assert it.total_cents == 6990
    assert it.transfers == 1


def test_walking_and_waiting_are_inside_the_envelope():
    it = journey_to_itinerary(DORTMUND_BERLIN)
    # 08:02 front door to 12:07 Berlin Hbf is 245 minutes, and every one of
    # them must be accounted for: walk, ride, the 15 minute change, ride.
    assert it.door_to_door_minutes == 245.0
    kinds = [leg.kind.value for leg in it.legs]
    assert kinds[0] == "access"
    assert "transfer" in kinds


def test_long_distance_time_counts_as_productive_but_walking_does_not():
    it = journey_to_itinerary(DORTMUND_BERLIN)
    assert it.productive_minutes == 104.0 + 97.0


def test_deutschlandticket_journeys_are_free_and_marked_regional():
    it = journey_to_itinerary(DORTMUND_BERLIN, deutschlandticket=True)
    assert it.total_cents == 0
    assert it.mode is Mode.RAIL_REGIONAL


def test_a_journey_without_a_quoted_fare_says_so_instead_of_guessing():
    payload = {**DORTMUND_BERLIN, "price": {"amount": None, "currency": "EUR"}}
    it = journey_to_itinerary(payload)
    assert it.total_cents == 0
    assert any("no fare" in n.lower() for n in it.notes)


def test_nightjet_is_detected_and_credited_with_the_hotel_saving():
    payload = {
        "legs": [
            {
                "origin": {"type": "stop", "id": "8011160", "name": "Berlin Hbf",
                           "location": {"latitude": 52.5250, "longitude": 13.3694}},
                "destination": {"type": "stop", "id": "8000261", "name": "München Hbf",
                                "location": {"latitude": 48.1402, "longitude": 11.5586}},
                "departure": "2026-10-14T23:05:00+02:00",
                "arrival": "2026-10-15T07:40:00+02:00",
                "line": {"name": "NJ 40491", "product": "nationalExpress", "mode": "train"},
            }
        ],
        "price": {"amount": 119.9, "currency": "EUR"},
    }
    it = journey_to_itinerary(payload)
    assert it.mode is Mode.NIGHT_RAIL
    assert it.total_cents == 11990 - 9500


def test_a_malformed_journey_returns_none_rather_than_exploding():
    assert journey_to_itinerary({"legs": []}) is None
    assert journey_to_itinerary({"legs": [{"line": {"name": "ICE 1"}}]}) is None
