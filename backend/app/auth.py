"""Closed-group access control.

Deliberately not a user system. For a first-round UAT you want to hand ten
people a code each, know which of them filed which feedback, and be able to
cut someone off by editing one environment variable. Anything more is
infrastructure you will throw away.

    UAT_CODES="rishabh:9f2a-plum,anna:4c81-oak,dev:0000-test"

The code goes in a signed cookie after first use, so testers enter it once.
Signing uses SESSION_SECRET; rotating that secret logs everyone out, which is
how you end a UAT round.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

COOKIE = "reiseplan_uat"
MAX_AGE_S = 14 * 24 * 3600


# Config is read per call, not at import. Module-level env reads force tests
# to reload the module, and a reload inside one test leaks its settings into
# every test that runs after it — which is exactly what happened here.
_EPHEMERAL_SECRET = secrets.token_hex(32)


def codes() -> dict[str, str]:
    """code -> tester name, parsed from UAT_CODES."""
    out: dict[str, str] = {}
    for entry in os.getenv("UAT_CODES", "").strip().split(","):
        if ":" not in entry:
            continue
        name, code = entry.split(":", 1)
        if name.strip() and code.strip():
            out[code.strip()] = name.strip()
    return out


def enabled() -> bool:
    return bool(codes())


def _secret() -> str:
    return os.getenv("SESSION_SECRET") or _EPHEMERAL_SECRET


def warn_if_open() -> None:
    """Called once at startup so an unguarded deploy is loud in the logs."""
    if not enabled():
        log.warning("UAT_CODES is empty — the API is OPEN. Set it before sharing a URL.")
    elif not os.getenv("SESSION_SECRET"):
        log.warning("SESSION_SECRET unset — sessions will not survive a restart.")


def _sign(tester: str, issued: int) -> str:
    msg = f"{tester}:{issued}".encode()
    mac = hmac.new(_secret().encode(), msg, hashlib.sha256).hexdigest()[:32]
    return f"{tester}:{issued}:{mac}"


def _verify(token: str) -> str | None:
    try:
        tester, issued_raw, mac = token.rsplit(":", 2)
        issued = int(issued_raw)
    except (ValueError, AttributeError):
        return None
    if time.time() - issued > MAX_AGE_S:
        return None
    expected = _sign(tester, issued).rsplit(":", 1)[1]
    return tester if hmac.compare_digest(mac, expected) else None


def mint(code: str) -> tuple[str, str] | None:
    """Exchange an invite code for (tester_name, session_token)."""
    for known, tester in codes().items():
        if hmac.compare_digest(code.strip(), known):
            return tester, _sign(tester, int(time.time()))
    return None


def current_tester(request: Request) -> str:
    """Dependency. Returns the tester name, or 401 with a machine-readable body."""
    if not enabled():
        return "open-access"
    token = request.cookies.get(COOKIE) or request.headers.get("x-uat-token", "")
    tester = _verify(token)
    if tester is None:
        raise HTTPException(401, "This build is invite-only. Enter your access code.")
    return tester
