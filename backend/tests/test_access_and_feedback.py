"""The gate and the feedback log. Both run with UAT_CODES actually set,
because an auth test against a disabled gate proves nothing."""

import pytest
from fastapi.testclient import TestClient

CODES = "rishabh:round1-plum,anna:round1-oak"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UAT_CODES", CODES)
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "uat.db"))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    from app.main import app  # no reload needed: config is read per call
    with TestClient(app) as c:
        yield c


def test_health_is_reachable_without_a_code(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["gated"] is True


def test_planning_without_a_code_is_401(client):
    assert client.get("/api/plan", params={
        "origin": "Berlin", "destination": "Hamburg"}).status_code == 401


def test_a_wrong_code_is_rejected(client):
    assert client.post("/api/login", json={"code": "hunter2"}).status_code == 401


def test_a_valid_code_identifies_the_tester_and_persists(client):
    r = client.post("/api/login", json={"code": "round1-oak"})
    assert r.status_code == 200 and r.json()["tester"] == "anna"
    assert client.get("/api/me").json()["tester"] == "anna"


def test_a_forged_cookie_does_not_pass(client):
    client.cookies.set("reiseplan_uat", "rishabh:9999999999:deadbeef")
    assert client.get("/api/me").status_code == 401


def test_feedback_is_attributed_and_shows_up_in_the_summary(client):
    client.post("/api/login", json={"code": "round1-plum"})
    payload = {
        "verdict": "wrong", "comment": "I'd have flown, I hate changing at Hannover",
        "query": {"origin": "Dortmund", "destination": "München", "preset": "balanced"},
        "ranking": [{"mode": "rail", "cents": 8990, "minutes": 330, "match": 100}],
    }
    assert client.post("/api/feedback", json=payload).json()["thanks"] is True

    s = client.get("/api/feedback/summary").json()
    assert s["counts"]["wrong"] == 1
    assert s["testers"][0]["tester"] == "rishabh"
    assert s["recent"][0]["o"] == "Dortmund"


def test_an_invented_verdict_is_rejected(client):
    client.post("/api/login", json={"code": "round1-plum"})
    assert client.post("/api/feedback", json={
        "verdict": "meh", "query": {}, "ranking": []}).status_code == 422


def test_feedback_exports_as_csv_for_the_round_review(client):
    client.post("/api/login", json={"code": "round1-oak"})
    client.post("/api/feedback", json={
        "verdict": "right", "comment": "matches what I'd book",
        "query": {"origin": "Berlin", "destination": "Hamburg"}, "ranking": []})
    r = client.get("/api/feedback/export.csv")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert "anna" in r.text and "right" in r.text
