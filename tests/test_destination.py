"""Tests for ships_ahoy.destination.resolve_ais_destination."""
from unittest.mock import MagicMock

import pytest

import ships_ahoy.destination as dest_module
from ships_ahoy.destination import resolve_ais_destination
from ais_destination_resolver.models import (
    Destination,
    GuidLocation,
    MatchResult,
    RouteEndpoint,
    RouteResolution,
)


# --- helpers ---

def _guid_loc(name):
    return GuidLocation(
        id=1, guid="084Y", full_code="US^084Y", unlocode=None,
        official_name=name, port_name=None, waterway_name=None,
        facility_type=None, latitude=None, longitude=None,
        mile=None, source="test", source_updated=None, notes=None,
    )


def _guid_ep(raw, normalized, location):
    return RouteEndpoint(
        raw=raw, normalized=normalized, endpoint_type="us_guid",
        guid_location=location, destination=None, confidence=1.0,
    )


def _undecoded_guid_ep(raw, normalized):
    return RouteEndpoint(
        raw=raw, normalized=normalized, endpoint_type="us_guid",
        guid_location=None, destination=None, confidence=0.0,
    )


def _route(raw, separator, endpoints, route_type="origin_to_destination"):
    return RouteResolution(
        raw_destination=raw,
        normalized_destination=raw.upper().replace(" ", ""),
        separator=separator,
        route_type=route_type,
        endpoints=endpoints,
        confidence=1.0,
    )


# --- fixtures ---

@pytest.fixture(autouse=True)
def reset_resolver(monkeypatch):
    """Reset module-level resolver cache between tests."""
    monkeypatch.setattr(dest_module, "_resolver", dest_module._NOT_INITIALIZED)


@pytest.fixture
def mock_resolver(monkeypatch):
    resolver = MagicMock()
    monkeypatch.setattr(dest_module, "_resolver", resolver)
    return resolver


# --- tests ---

def test_two_decoded_guid_endpoints(mock_resolver):
    """Route with both GUIDs decoded → 'traveling from X to Y'."""
    result = _route(
        "US^084Y>0WQB", ">",
        [
            _guid_ep("US^084Y", "US^084Y", _guid_loc("New Madrid Flg")),
            _guid_ep("0WQB", "US^0WQB", _guid_loc("Cairo Lock")),
        ],
    )
    mock_resolver.resolve_route.return_value = result

    assert resolve_ais_destination("US^084Y>0WQB") == "traveling from New Madrid Flg to Cairo Lock"


def test_partial_guid_decode_shows_raw_code(mock_resolver):
    """Route with one undecoded GUID → raw code used for that endpoint."""
    result = _route(
        "US^084Y>0WQB", ">",
        [
            _guid_ep("US^084Y", "US^084Y", _guid_loc("New Madrid Flg")),
            _undecoded_guid_ep("0WQB", "US^0WQB"),
        ],
    )
    mock_resolver.resolve_route.return_value = result

    assert resolve_ais_destination("US^084Y>0WQB") == "traveling from New Madrid Flg to US^0WQB"


def test_single_guid_decoded_at_anchor(mock_resolver):
    """Single GUID endpoint with no separator → 'at anchor at X'."""
    result = RouteResolution(
        raw_destination="US^084Y",
        normalized_destination="US^084Y",
        separator=None,
        route_type="single_endpoint",
        endpoints=[_guid_ep("US^084Y", "US^084Y", _guid_loc("Cairo Lock"))],
        confidence=1.0,
    )
    mock_resolver.resolve_route.return_value = result

    assert resolve_ais_destination("US^084Y") == "at anchor at Cairo Lock"


def test_single_guid_undecoded_shows_raw_code(mock_resolver):
    """Single GUID endpoint, not in DB → raw code in 'at anchor' message."""
    result = RouteResolution(
        raw_destination="US^084Y",
        normalized_destination="US^084Y",
        separator=None,
        route_type="single_endpoint",
        endpoints=[_undecoded_guid_ep("US^084Y", "US^084Y")],
        confidence=0.0,
    )
    mock_resolver.resolve_route.return_value = result

    assert resolve_ais_destination("US^084Y") == "at anchor at US^084Y"


def test_plain_text_returns_canonical_name(mock_resolver):
    """Plain-text destination → canonical name from fuzzy resolver."""
    destination = Destination(
        id=1, locode="USNOL", canonical_name="New Orleans",
        aliases=["NOLA"], state="LA", country_code="US",
        waterway="Mississippi River", river_mile=95.0,
        latitude=29.95, longitude=-90.07,
        destination_type="port", status="active",
        source="seed", source_updated=None, is_active=True, notes=None,
    )
    match = MatchResult(
        raw_destination="NOLA",
        normalized_destination="nola",
        destination=destination,
        confidence=0.95,
        match_method="exact_alias",
        ambiguous=False,
        alternatives=[],
    )
    mock_resolver.resolve.return_value = match

    assert resolve_ais_destination("NOLA") == "New Orleans"


def test_resolver_unavailable_returns_none(monkeypatch):
    """When resolver is None (no DB), function returns None."""
    monkeypatch.setattr(dest_module, "_resolver", None)
    assert resolve_ais_destination("US^084Y>0WQB") is None


def test_empty_input_returns_none(mock_resolver):
    """Empty string → None (no display)."""
    assert resolve_ais_destination("") is None
