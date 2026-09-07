"""UAT feedback capture.

The useful thing about round-one feedback is not the thumbs. It is being able
to reconstruct exactly what the tester was looking at when they filed it, so
you can replay the search and see whether the ranking was wrong or the
explanation was. Every row therefore stores the full query and the ranked
result alongside the verdict.

SQLite because a UAT round produces hundreds of rows, not millions. Point
DATABASE_PATH at a mounted volume so a redeploy does not lose the round.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

_lock = Lock()


def db_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", "/data/uat.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  TEXT NOT NULL,
  tester      TEXT NOT NULL,
  verdict     TEXT NOT NULL CHECK (verdict IN ('right','wrong','unsure')),
  comment     TEXT,
  query       TEXT NOT NULL,
  ranking     TEXT NOT NULL,
  build       TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_tester ON feedback(tester);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at);
"""


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)


def record(
    *, tester: str, verdict: str, comment: str | None,
    query: dict, ranking: list[dict], build: str | None,
) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO feedback (created_at, tester, verdict, comment, query, ranking, build)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                datetime.now(UTC).isoformat(),
                tester, verdict, (comment or "").strip()[:2000],
                json.dumps(query, default=str),
                json.dumps(ranking, default=str)[:20000],
                build,
            ),
        )
        return int(cur.lastrowid or 0)


def summary() -> dict:
    """What you actually want to read on a Monday morning."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT verdict, COUNT(*) n FROM feedback GROUP BY verdict"
        ).fetchall()
        testers = conn.execute(
            "SELECT tester, COUNT(*) n, MAX(created_at) last FROM feedback"
            " GROUP BY tester ORDER BY n DESC"
        ).fetchall()
        recent = conn.execute(
            "SELECT id, created_at, tester, verdict, comment,"
            " json_extract(query,'$.origin') o, json_extract(query,'$.destination') d,"
            " json_extract(query,'$.preset') p"
            " FROM feedback ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return {
        "counts": {r["verdict"]: r["n"] for r in rows},
        "testers": [dict(r) for r in testers],
        "recent": [dict(r) for r in recent],
    }


def export_rows() -> list[dict]:
    with _lock, _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()]
