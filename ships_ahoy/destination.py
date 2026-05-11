"""Destination resolver integration for the ticker.

Lazily loads the ais_destination_resolver package and its inland-ports
database on first use. Falls back silently (returns None) if the package
is unavailable or the database has not been built yet.

Usage::

    from ships_ahoy.destination import resolve_destination

    canonical = resolve_destination("NOLA", lat=29.95, lon=-90.07)
    # "New Orleans"
"""

import os
from typing import Optional

_RESOLVER_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ais_destination_resolver", "data", "inland_ports.db",
)

_NOT_INITIALIZED = object()
_resolver = _NOT_INITIALIZED


def _get_resolver():
    global _resolver
    if _resolver is not _NOT_INITIALIZED:
        return _resolver
    try:
        from ais_destination_resolver.db import load_destinations
        from ais_destination_resolver.resolver import DestinationResolver
        destinations = load_destinations(_RESOLVER_DB)
        _resolver = DestinationResolver(destinations) if destinations else None
    except Exception:
        _resolver = None
    return _resolver


def resolve_destination(
    raw: str,
    *,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Optional[str]:
    """Return the canonical destination name for a raw AIS string, or None.

    Returns None when the resolver is not available, the database is missing,
    or the best match confidence falls below the acceptance threshold.
    The caller should fall back to title-casing the raw string in that case.
    """
    resolver = _get_resolver()
    if resolver is None:
        return None
    result = resolver.resolve(raw, latitude=lat, longitude=lon)
    if result.destination is not None:
        return result.destination.canonical_name
    return None
