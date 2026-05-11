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
