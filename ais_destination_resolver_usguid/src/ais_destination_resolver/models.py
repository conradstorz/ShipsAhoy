"""Data models for AIS destination resolution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    """A normalized inland-waterway destination candidate."""

    id: int | None
    locode: str | None
    canonical_name: str
    aliases: list[str]
    state: str | None
    country_code: str
    waterway: str | None
    river_mile: float | None
    latitude: float | None
    longitude: float | None
    destination_type: str
    status: str | None
    source: str
    source_updated: str | None
    is_active: bool
    notes: str | None


@dataclass(frozen=True)
class GuidLocation:
    """A USCG U.S. Geographic Unique ID location candidate.

    U.S. GUIDs are commonly broadcast in AIS destination/origination fields as
    strings such as ``US^0WQB``.  NAVCEN publishes the official lookup table.
    """

    id: int | None
    guid: str
    full_code: str
    unlocode: str | None
    official_name: str
    port_name: str | None
    waterway_name: str | None
    facility_type: str | None
    latitude: float | None
    longitude: float | None
    mile: float | None
    source: str
    source_updated: str | None
    notes: str | None


@dataclass(frozen=True)
class MatchResult:
    """Result returned by the AIS destination resolver."""

    raw_destination: str
    normalized_destination: str
    destination: Destination | None
    confidence: float
    match_method: str
    ambiguous: bool
    alternatives: list[tuple[Destination, float]]
    notes: str | None = None


@dataclass(frozen=True)
class RouteEndpoint:
    """One endpoint parsed from an AIS route-style destination field."""

    raw: str
    normalized: str
    endpoint_type: str
    guid_location: GuidLocation | None
    destination: Destination | None
    confidence: float
    notes: str | None = None


@dataclass(frozen=True)
class RouteResolution:
    """Parsed and resolved form of a route-style AIS destination field."""

    raw_destination: str
    normalized_destination: str
    separator: str | None
    route_type: str
    endpoints: list[RouteEndpoint]
    confidence: float
    notes: str | None = None
