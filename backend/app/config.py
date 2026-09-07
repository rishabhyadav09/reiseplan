from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    # Point this at your OWN db-vendo-client container in anything but a demo.
    # The shared instance at v6.db.transport.rest is rate limited to 100 req/min
    # across every user on the internet, and DB blocks aggressively.
    # Transitous: community-run MOTIS, ~40 countries of GTFS. Read their usage
    # policy before pointing real traffic at it, and cache aggressively.
    motis_base: str = os.getenv("MOTIS_BASE", "https://api.transitous.org")

    # Kept so the DB adapter can be switched back on if DB stops blocking.
    db_api_base: str = os.getenv("DB_API_BASE", "https://v6.db.transport.rest")
    use_db_rail: bool = os.getenv("USE_DB_RAIL", "false").lower() == "true"
    user_agent: str = os.getenv("USER_AGENT", "reiseplan-poc (set a real contact)")

    redis_url: str | None = os.getenv("REDIS_URL")
    cache_ttl_journeys: int = int(os.getenv("CACHE_TTL_JOURNEYS", "300"))
    cache_ttl_locations: int = int(os.getenv("CACHE_TTL_LOCATIONS", "2592000"))

    http_timeout_s: float = float(os.getenv("HTTP_TIMEOUT_S", "12"))
    db_max_concurrency: int = int(os.getenv("DB_MAX_CONCURRENCY", "4"))

    enable_flix: bool = os.getenv("ENABLE_FLIX", "false").lower() == "true"

    # Modelled airfares are shown to nobody by default. A stranger reading
    # "EUR 135.71" does not care that a badge says "modelled"; they read it as
    # a price. Turn this on only once a real fare feed is wired.
    enable_air: bool = os.getenv("ENABLE_AIR", "false").lower() == "true"
    duffel_token: str | None = os.getenv("DUFFEL_TOKEN")

    deutschlandticket_monthly_cents: int = int(os.getenv("DTICKET_CENTS", "5800"))


settings = Settings()
