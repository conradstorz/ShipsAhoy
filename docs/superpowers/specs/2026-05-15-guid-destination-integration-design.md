# GUID Destination Integration Design

**Date:** 2026-05-15  
**Status:** Approved

## Overview

Integrate the new `ais_destination_resolver_usguid` package into the main ShipsAhoy project so that USCG U.S. GUID route strings (e.g. `US^084Y>0WQB`) are decoded to human-readable names on the LED ticker display.

## Background

AIS destination fields on inland towboats frequently contain USCG route codes rather than plain text. These use U.S. Geographic Unique IDs (GUIDs) published by USCG NAVCEN, e.g.:

- `US^084Y>0WQB` — origin GUID to destination GUID
- `US^084Y` — single endpoint (anchored/moored)
- `USCIR<>USCIR` — operating within a UN/LOCODE area

The existing resolver only handles plain-text fuzzy matching. The new `ais_destination_resolver_usguid` package (same Python package name `ais_destination_resolver`) adds:

- `GuidLocation` model and `us_guid_locations` DB table
- `uscg_route.py` — tokenizer/parser for route-style fields
- `guid_importer.py` — downloads/imports the official NAVCEN GUID CSV
- `DestinationResolver.resolve_route()` — resolves full route strings

## Files Changed

| File | Change |
|---|---|
| `pyproject.toml` | Re-point `ais-destination-resolver` source path to `ais_destination_resolver_usguid` |
| `ships_ahoy/destination.py` | Update DB path; load GUID locations; add `resolve_ais_destination()` |
| `ships_ahoy/ticker_content.py` | Replace `resolve_destination` call with `resolve_ais_destination` |

Nothing else changes.

## `destination.py` Design

### Initialization

`_get_resolver()` is extended to:
1. Call `load_destinations(db_path)` — existing behavior
2. Call `load_guid_locations(db_path)` — new
3. Pass both to `DestinationResolver(destinations, guid_locations=guid_locations)`

DB path updates from `ais_destination_resolver/data/inland_ports.db` to `ais_destination_resolver_usguid/data/inland_ports.db`.

### New public function

```python
def resolve_ais_destination(
    raw: str,
    *,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Optional[str]:
```

Logic:

1. Run `parse_ais_route(raw)` from `uscg_route.py`
2. If the parsed result has a separator **or** any token has `token_type == "us_guid"`:
   - Call `resolver.resolve_route(raw, latitude=lat, longitude=lon)`
   - Format and return via `_format_route(result)`
3. Otherwise: call `resolver.resolve(raw, latitude=lat, longitude=lon)` and return `result.destination.canonical_name` or `None`

Returns `None` on any failure (resolver unavailable, DB missing) — caller falls back to `.title()`.

### Format helper `_format_route(result: RouteResolution) -> str`

| Case | Output |
|---|---|
| 2+ endpoints with separator, both decoded | `"traveling from {origin_name} to {dest_name}"` |
| 2+ endpoints with separator, partial | `"traveling from {origin} to {dest}"` where undecoded = raw code |
| Single `us_guid` token, no separator | `"at anchor at {name}"` (raw code if undecoded) |
| Single non-GUID token | canonical name string (same as plain-text path) |

An endpoint is "decoded" if its `RouteEndpoint.guid_location` is not `None` (for GUID tokens) or `RouteEndpoint.destination` is not `None` (for text/LOCODE tokens). Undecoded endpoints fall back to `endpoint.normalized` (the normalized raw code).

### Backward compatibility

`resolve_destination()` remains in place, unchanged, so any other call sites are unaffected.

## `ticker_content.py` Change

One line change at line 154:

```python
# before
destination = resolve_destination(raw_dest, lat=lat, lon=lon) or raw_dest.title()

# after
destination = resolve_ais_destination(raw_dest, lat=lat, lon=lon) or raw_dest.title()
```

Update the import at line 38 accordingly.

## Error Handling

All resolver errors are caught inside `_get_resolver()` — sets `_resolver = None`. `resolve_ais_destination()` returns `None` on any exception, so `ticker_content.py` always has the `.title()` fallback. No new error paths are introduced.

## Data Setup

The `us_guid_locations` table is populated by running:

```bash
cd ais_destination_resolver_usguid
uv run ais-dest download-guid-csv
uv run ais-dest import-guid-csv data/sources/GUID-Sorted-By-Latitude-Longitude-Type-Name.csv
```

Without this step, GUID tokens parse correctly but resolve to their raw code strings.

## Testing

- Existing `resolve_destination` tests remain valid (function is unchanged).
- New unit tests for `resolve_ais_destination` covering:
  - Two-endpoint GUID route, both decoded
  - Two-endpoint GUID route, one undecoded
  - Single GUID endpoint (at anchor)
  - Plain text passthrough
  - Empty/None input
  - Resolver unavailable (no DB)
