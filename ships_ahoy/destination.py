"""Destination resolver integration for the ticker.

Lazily loads the ais_destination_resolver package and its database on first
use. Falls back silently (returns None) if the package is unavailable or the
database has not been built yet.

Usage::

    from ships_ahoy.destination import resolve_ais_destination

    text = resolve_ais_destination("US^084Y>0WQB", lat=37.0, lon=-89.1)
    # "traveling from New Madrid Flg to Cairo Lock"

    text = resolve_ais_destination("NOLA", lat=29.95, lon=-90.07)
    # "New Orleans"
"""

import os
from typing import Optional

from loguru import logger

_RESOLVER_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ais_destination_resolver_usguid", "data", "inland_ports.db",
)

_NOT_INITIALIZED = object()
_resolver = _NOT_INITIALIZED


def _get_resolver():
    global _resolver
    if _resolver is not _NOT_INITIALIZED:
        return _resolver
    try:
        from ais_destination_resolver.db import load_destinations, load_guid_locations
        from ais_destination_resolver.resolver import DestinationResolver
        destinations = load_destinations(_RESOLVER_DB)
        guid_locations = load_guid_locations(_RESOLVER_DB)
        _resolver = DestinationResolver(destinations, guid_locations=guid_locations)
        logger.info("Destination resolver loaded from {}", _RESOLVER_DB)
    except Exception:
        logger.exception("Destination resolver failed to initialize (DB: {})", _RESOLVER_DB)
        _resolver = None
    return _resolver


def _endpoint_name(endpoint) -> str:
    """Return a display name for one RouteEndpoint."""
    if endpoint.guid_location is not None:
        return endpoint.guid_location.official_name
    if endpoint.destination is not None:
        return endpoint.destination.canonical_name
    return endpoint.normalized


def _format_route(result) -> str:
    """Format a RouteResolution into a human-readable ticker string."""
    endpoints = result.endpoints
    if not endpoints:
        return ""

    if result.separator is not None and len(endpoints) >= 2:
        origin = _endpoint_name(endpoints[0])
        dest = _endpoint_name(endpoints[-1])
        if not origin or not dest:
            return ""
        return f"traveling from {origin} to {dest}"

    ep = endpoints[0]
    if ep.endpoint_type == "us_guid":
        return f"at anchor at {_endpoint_name(ep)}"
    return _endpoint_name(ep)


def resolve_ais_destination(
    raw: str,
    *,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Optional[str]:
    """Resolve a raw AIS destination field to a human-readable ticker string.

    Handles both plain-text destinations and USCG route strings (e.g.
    ``US^084Y>0WQB``). Returns None when resolution fails; the caller should
    fall back to ``raw.title()``.
    """
    if not raw or not raw.strip():
        return None
    try:
        resolver = _get_resolver()
        if resolver is None:
            return None
        upper = raw.strip().upper().replace(" ", "")
        # Require an explicit US^ prefix or route separator to trigger GUID route
        # resolution. Using parse_ais_route token classification would also catch
        # bare 4-char GUIDs (e.g. "0WQB") but would misclassify plain-text port
        # abbreviations like "NOLA" as GUIDs. The trade-off favours plain-text
        # accuracy; bare GUIDs without US^ fall back to .title() at the call site.
        is_route = "US^" in upper or any(sep in upper for sep in (">", "<"))
        if is_route:
            result = resolver.resolve_route(raw, latitude=lat, longitude=lon)
            if result.separator is not None and not any(
                ep.guid_location is not None or ep.destination is not None
                for ep in result.endpoints
            ):
                return None
            return _format_route(result) or None
        result = resolver.resolve(raw, latitude=lat, longitude=lon)
        if result.destination is not None:
            return result.destination.canonical_name
        return None
    except Exception:
        logger.debug("resolve_ais_destination failed for {!r}", raw, exception=True)
        return None


