"""Geographic distance and bearing utilities for ShipsAhoy.

All functions operate on WGS-84 decimal degrees.

Usage::

    km = haversine_km(ship.latitude, ship.longitude, home_lat, home_lon)
    direction = bearing_to_cardinal(bearing_degrees(...))
    if is_noteworthy(ship.latitude, ship.longitude, home_lat, home_lon, 50.0):
        ...
"""

import math


_EARTH_RADIUS_KM = 6371.0

_CARDINALS = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]


def haversine_km(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Return the great-circle distance in kilometres between two points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_degrees(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Return the initial bearing in degrees (0-360) from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bearing_to_cardinal(degrees: float) -> str:
    """Convert a bearing in degrees to a 16-point cardinal string."""
    index = round(degrees / 22.5) % 16
    return _CARDINALS[index]


def distance_info(
    home_lat: float,
    home_lon: float,
    ship_lat: float,
    ship_lon: float,
) -> tuple[float, str]:
    """Return (distance_km rounded to 1dp, cardinal direction) from home to ship."""
    km = round(haversine_km(home_lat, home_lon, ship_lat, ship_lon), 1)
    cardinal = bearing_to_cardinal(bearing_degrees(home_lat, home_lon, ship_lat, ship_lon))
    return km, cardinal


def is_noteworthy(
    ship_lat: float,
    ship_lon: float,
    home_lat: float,
    home_lon: float,
    threshold_km: float,
) -> bool:
    """Return True if the ship is within *threshold_km* of the home location."""
    return haversine_km(ship_lat, ship_lon, home_lat, home_lon) <= threshold_km
