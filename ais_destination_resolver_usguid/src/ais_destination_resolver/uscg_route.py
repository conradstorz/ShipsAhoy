"""Parse USCG AIS destination/origination route strings.

The USCG AIS Encoding Guide allows the AIS destination field to contain
UN/LOCODEs and U.S. Geographic Unique IDs (US/GUIDs).  Inland towboats often
broadcast compact route strings like ``US^084Y>0WQB`` where the second endpoint
inherits the ``US^`` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


GUID_RE = re.compile(r"^(?:US\^)?[0-9A-Z]{4}$")
US_GUID_RE = re.compile(r"^US\^[0-9A-Z]{4}$")
UNLOCODE_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}$")
SEPARATORS = ["><", "<<", "<>", ">", "<"]

ROUTE_TYPE_BY_SEPARATOR = {
    ">": "origin_to_destination",
    "<": "destination_to_origin_or_reverse",
    "><": "round_trip_or_scheduled_route",
    "<<": "anchored_moored_or_on_station",
    "<>": "operating_within_area",
}


@dataclass(frozen=True)
class ParsedRouteToken:
    """One parsed endpoint token from an AIS destination/origination field."""

    raw: str
    normalized: str
    token_type: str


@dataclass(frozen=True)
class ParsedRoute:
    """Tokenizer result for a route-style AIS destination/origination field."""

    raw_destination: str
    normalized_destination: str
    separator: str | None
    route_type: str
    tokens: list[ParsedRouteToken]
    notes: str | None = None


def normalize_route_text(value: str) -> str:
    """Normalize an AIS route field while preserving USCG route punctuation."""

    return "".join(str(value or "").upper().strip().split())


def normalize_guid(value: str, *, inherit_us_prefix: bool = True) -> str:
    """Normalize a U.S. GUID token to the canonical ``US^XXXX`` form.

    :param value: Raw token such as ``US^0WQB`` or ``0WQB``.
    :param inherit_us_prefix: Treat bare four-character tokens as U.S. GUIDs.
    :return: Canonical GUID string.
    """

    cleaned = normalize_route_text(value)
    if US_GUID_RE.match(cleaned):
        return cleaned
    if inherit_us_prefix and GUID_RE.match(cleaned):
        bare = cleaned.removeprefix("US^")
        return f"US^{bare}"
    return cleaned


def classify_token(value: str, *, previous_was_us_guid: bool = False) -> ParsedRouteToken:
    """Classify a route endpoint as US/GUID, UN/LOCODE, text, or empty."""

    cleaned = normalize_route_text(value)
    if not cleaned:
        return ParsedRouteToken(raw=value, normalized="", token_type="empty")

    if US_GUID_RE.match(cleaned):
        return ParsedRouteToken(raw=value, normalized=cleaned, token_type="us_guid")

    if previous_was_us_guid and GUID_RE.match(cleaned):
        return ParsedRouteToken(raw=value, normalized=normalize_guid(cleaned), token_type="us_guid")

    if UNLOCODE_RE.match(cleaned):
        return ParsedRouteToken(raw=value, normalized=cleaned, token_type="unlocode")

    # Some broadcasts omit the US^ prefix even on the first token.  We only make
    # that assumption when the token is exactly four base-36-looking characters.
    if GUID_RE.match(cleaned):
        return ParsedRouteToken(raw=value, normalized=normalize_guid(cleaned), token_type="us_guid")

    return ParsedRouteToken(raw=value, normalized=cleaned, token_type="text")


def parse_ais_route(raw_destination: str) -> ParsedRoute:
    """Parse a raw AIS destination field into route tokens.

    Examples:
        ``US^084Y>0WQB`` becomes ``US^084Y`` and ``US^0WQB``.
        ``USCIR<>USCIR`` becomes two UN/LOCODE endpoints.
    """

    normalized = normalize_route_text(raw_destination)
    if not normalized:
        return ParsedRoute(raw_destination, normalized, None, "empty", [], "No destination text.")

    separator = next((candidate for candidate in SEPARATORS if candidate in normalized), None)
    if separator is None:
        token = classify_token(normalized)
        return ParsedRoute(
            raw_destination=raw_destination,
            normalized_destination=normalized,
            separator=None,
            route_type="single_endpoint",
            tokens=[token],
        )

    pieces = normalized.split(separator)
    tokens: list[ParsedRouteToken] = []
    previous_was_us_guid = False
    for piece in pieces:
        token = classify_token(piece, previous_was_us_guid=previous_was_us_guid)
        tokens.append(token)
        previous_was_us_guid = token.token_type == "us_guid"

    return ParsedRoute(
        raw_destination=raw_destination,
        normalized_destination=normalized,
        separator=separator,
        route_type=ROUTE_TYPE_BY_SEPARATOR.get(separator, "unknown_route"),
        tokens=tokens,
    )
