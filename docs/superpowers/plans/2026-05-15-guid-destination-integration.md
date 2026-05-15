# GUID Destination Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the new `ais_destination_resolver_usguid` package into the ShipsAhoy ticker so USCG GUID route strings like `US^084Y>0WQB` display as "traveling from New Madrid Flg to Cairo Lock".

**Architecture:** Switch the `pyproject.toml` source path to the new package (same import name, superset of old), extend `ships_ahoy/destination.py` with a `resolve_ais_destination()` function that auto-detects route vs plain-text and formats the result, then update the single call site in `ticker_content.py`.

**Tech Stack:** Python 3.11+, `uv`, `rapidfuzz`, `ais_destination_resolver` (package), `sqlite3`, `pytest`

---

## File Map

| File | Action |
|---|---|
| `pyproject.toml` | Modify — change `ais-destination-resolver` source path |
| `ships_ahoy/destination.py` | Modify — update DB path, extend `_get_resolver()`, add `_format_route()`, `_endpoint_name()`, `resolve_ais_destination()` |
| `ships_ahoy/ticker_content.py` | Modify — update import + one call site |
| `tests/test_destination.py` | Create — unit tests for `resolve_ais_destination` |

---

## Task 1: Switch package source and sync

**Files:**
- Modify: `pyproject.toml:28`

- [ ] **Step 1: Update the source path**

In `pyproject.toml`, change:
```toml
[tool.uv.sources]
ais-destination-resolver = { path = "ais_destination_resolver" }
```
to:
```toml
[tool.uv.sources]
ais-destination-resolver = { path = "ais_destination_resolver_usguid" }
```

- [ ] **Step 2: Sync dependencies**

```bash
uv sync
```

Expected: resolves successfully, no errors. The installed package now comes from `ais_destination_resolver_usguid/src/`.

- [ ] **Step 3: Verify new modules are importable**

```bash
uv run python -c "from ais_destination_resolver.uscg_route import parse_ais_route; from ais_destination_resolver.db import load_guid_locations; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Verify existing tests still pass**

```bash
uv run pytest tests/ -v -x
```

Expected: all tests pass (resolver returns `None` gracefully — DB path still points to old directory at this point, which is fine).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: switch ais-destination-resolver source to usguid package"
```

---

## Task 2: Write failing tests for `resolve_ais_destination`

**Files:**
- Create: `tests/test_destination.py`

- [ ] **Step 1: Create the test file**

Create `tests/test_destination.py` with this content:

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
uv run pytest tests/test_destination.py -v
```

Expected: all 7 tests fail with `ImportError: cannot import name 'resolve_ais_destination' from 'ships_ahoy.destination'`.

---

## Task 3: Implement `resolve_ais_destination` in `destination.py`

**Files:**
- Modify: `ships_ahoy/destination.py`

- [ ] **Step 1: Replace the entire file**

Replace `ships_ahoy/destination.py` with:

```python
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
    except Exception:
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
        from ais_destination_resolver.uscg_route import parse_ais_route
        resolver = _get_resolver()
        if resolver is None:
            return None
        parsed = parse_ais_route(raw)
        is_route = parsed.separator is not None or any(
            t.token_type == "us_guid" for t in parsed.tokens
        )
        if is_route:
            result = resolver.resolve_route(raw, latitude=lat, longitude=lon)
            return _format_route(result) or None
        result = resolver.resolve(raw, latitude=lat, longitude=lon)
        if result.destination is not None:
            return result.destination.canonical_name
        return None
    except Exception:
        return None


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
```

- [ ] **Step 2: Run the new tests**

```bash
uv run pytest tests/test_destination.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add ships_ahoy/destination.py tests/test_destination.py
git commit -m "feat: add resolve_ais_destination with GUID route support"
```

---

## Task 4: Update the call site in `ticker_content.py`

**Files:**
- Modify: `ships_ahoy/ticker_content.py:38,154`

- [ ] **Step 1: Update the import line**

In `ships_ahoy/ticker_content.py`, change line 38 from:
```python
from ships_ahoy.destination import resolve_destination
```
to:
```python
from ships_ahoy.destination import resolve_ais_destination
```

- [ ] **Step 2: Update the call site**

In `ships_ahoy/ticker_content.py`, change line ~154 from:
```python
        destination = resolve_destination(raw_dest, lat=lat, lon=lon) or raw_dest.title()
```
to:
```python
        destination = resolve_ais_destination(raw_dest, lat=lat, lon=lon) or raw_dest.title()
```

- [ ] **Step 3: Run the ticker content tests**

```bash
uv run pytest tests/test_ticker_content.py -v
```

Expected: all tests pass (they don't patch the resolver, so it returns `None` and the `.title()` fallback is used — same as before).

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add ships_ahoy/ticker_content.py
git commit -m "feat: wire resolve_ais_destination into ticker content builder"
```

---

## Self-Review Checklist (completed inline)

- **Spec coverage:** pyproject.toml path switch ✓ · DB path update ✓ · `_get_resolver()` loads GUID locations ✓ · `_format_route()` all four cases ✓ · `resolve_ais_destination()` ✓ · `resolve_destination()` backward compat ✓ · `ticker_content.py` import + call ✓ · all 6 test cases from spec ✓ (plus empty-input = 7 total)
- **Placeholders:** none
- **Type consistency:** `_endpoint_name`, `_format_route`, `resolve_ais_destination` — names consistent across all tasks
