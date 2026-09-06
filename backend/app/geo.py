from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_KM = 6371.0

# Grams CO2 equivalent per passenger-kilometre, German averages.
# Source shape: Umweltbundesamt TREMOD categories. Adjust in one place.
CO2_G_PER_PKM = {
    "rail_long": 32,      # Fernverkehr
    "rail_regional": 54,  # Nahverkehr
    "coach": 29,          # Fernlinienbus
    "air_domestic": 214,  # Inlandsflug, before radiative forcing uplift
    "car_solo": 154,
}
AIR_RFI_MULTIPLIER = 1.7   # non-CO2 warming; applied only when asked for
AIR_FIXED_G = 8000         # takeoff and landing cycle, roughly


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(a))
