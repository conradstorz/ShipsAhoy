# Plan: Fill Missing DB Data Points

**TL;DR:** Five categories of data are received/computed but never persisted. Four sequential phases: schema migrations → data-layer changes → service-layer consumers → cleanup. Each phase is independently verifiable.

---

## Phase 1 — Schema Migrations *(all parallel, no dependencies)*

Add columns via the existing try/except `ALTER TABLE` migration pattern in `init_db()` (`ships_ahoy/db.py`):

| Gap | New columns → table |
|-----|---------------------|
| Gap 1 — AIS type-5 | `imo TEXT`, `callsign TEXT`, `draught REAL`, `eta TEXT`, `dim_bow INT`, `dim_stern INT`, `dim_port INT`, `dim_starboard INT` → `ships` |
| Gap 2 — Resolved destination | `destination_resolved TEXT` → `ships` |
| Gap 3 — Spatial cache | `distance_km REAL`, `bearing TEXT` → `ships` |
| Gap 4 — Type label | `ship_type_label TEXT` → `ships` |
| Gap 5 — Event ship name | `ship_name TEXT` → `events` |

---

## Phase 2 — Data Layer *(depends on Phase 1)*

### 2a. Extend `ShipInfo` dataclass (`ships_ahoy/ship_tracker.py`)
Add 8 optional fields:
- `imo: Optional[str] = None`
- `callsign: Optional[str] = None`
- `draught: Optional[float] = None`
- `eta: Optional[str] = None`  *(AIS ETA lacks a year; stored as plain string e.g. `"05-12 14:30"`)*
- `dim_bow: Optional[int] = None`
- `dim_stern: Optional[int] = None`
- `dim_port: Optional[int] = None`
- `dim_starboard: Optional[int] = None`

### 2b. Extend `ShipTracker.update()` (`ships_ahoy/ship_tracker.py`)
For AIS message types that carry type-5 fields (type 5, type 24 Part B), read:
- `msg.imo` → `imo` (sanitize sentinel `0` → `None`)
- `msg.callsign` (strip `@` padding) → `callsign`
- `msg.draught` (sentinel `0.0` → `None`) → `draught`
- `msg.eta` → `eta` (serialize as `"MM-DD HH:MM"` string or `None`)
- `msg.to_bow`, `msg.to_stern`, `msg.to_port`, `msg.to_starboard` → dimensions (sentinel `0` → `None`)

### 2c. Extend `upsert_ship()` (`ships_ahoy/db.py`)
- Include all 8 new AIS fields with `COALESCE` so existing non-null values are not overwritten by `None`
- Compute and store `ship_type_label` from `ship_type` via canonical function (see 2f)
- Call `resolve_destination()` and store `destination_resolved` when `destination` is non-null and either destination changed or `destination_resolved` is currently `NULL`

### 2d. Extend `write_event()` (`ships_ahoy/db.py`)
- Add `ship_name: Optional[str] = None` parameter; include in `INSERT`
- Update all call sites in `services/ais_service.py` (and any other callers) to pass the ship's name

### 2e. New `update_ship_spatial(conn, mmsi, home_lat, home_lon)` (`ships_ahoy/db.py`)
- Reads `latitude`, `longitude` for the given `mmsi`
- Computes `distance_km` and `bearing` via `distance_info()` from `ships_ahoy/distance.py`
- Writes back: `UPDATE ships SET distance_km=?, bearing=? WHERE mmsi=?`
- Called by `ais_service.py` after each position-bearing `upsert_ship()`

### 2f. Canonical `ship_type_label(ship_type: Optional[int]) -> str` (`ships_ahoy/distance.py`)
- Consolidates the currently inconsistent `_ship_type_label()` in `web_service.py` (`"Cargo"`) and `_type_label()` in `ticker_content.py` (`"cargo vessel"`) into a single title-case format: `"Cargo"`, `"Tanker"`, `"Passenger"`, `"Fishing"`, `"Service"`, `str(ship_type)` fallback
- Both existing private functions replaced with calls to this shared function

---

## Phase 3 — Service Layer Consumers *(depends on Phase 2)*

### 3a. `services/ais_service.py`
- After `upsert_ship(conn, ship)`, call `update_ship_spatial(conn, ship.mmsi, home_lat, home_lon)` when home is configured
- Pass `ship.name` to all `write_event()` call sites

### 3b–3c. `services/web_service.py` — `index()` and `ship_detail()` routes
- Remove inline `distance_info()` computation loop
- Remove inline `_ship_type_label()` calls
- Read `distance_km`, `bearing`, `ship_type_label` directly from DB row

### 3d. `services/web_service.py` — `events()` route
- Remove `ship_names` join dict construction
- Read `ship_name` directly from event row

### 3e. `ships_ahoy/ticker_content.py` — `_extract_facts()`
- Read `destination_resolved` from `ship_row` instead of calling `resolve_destination()` at render time
- Fallback: if `destination_resolved` is `None` and `destination` is non-null, fall back to `raw.title()`
- Read `ship_type_label` from `ship_row` instead of calling `_type_label()`
- Confirm `distance_km` and `bearing` are read from DB row (caller already passes `ship_row`)

### 3f. `ships_ahoy/ticker_content.py` — `build_playlist()` / `db.get_ships_in_range()`
- Replace Python-side haversine filter with SQL: `WHERE distance_km IS NOT NULL AND distance_km <= ?`
- Eliminates fetching all positioned ships to Python for filtering

---

## Phase 4 — Cleanup *(depends on Phase 3)*

- Remove private `_ship_type_label()` from `services/web_service.py`
- Remove private `_type_label()` from `ships_ahoy/ticker_content.py`
- Confirm `resolve_destination()` is no longer called at render/display time anywhere

---

## Verification Checklist

1. `pytest tests/` passes before and after all changes (no regressions)
2. `sqlite3 ships.db ".schema ships"` — all 12 new columns present
3. `sqlite3 ships.db ".schema events"` — `ship_name` column present
4. Ingest an AIS type-5 fixture; query `SELECT imo, callsign, draught FROM ships WHERE mmsi=?` — populated
5. `SELECT destination, destination_resolved FROM ships WHERE destination IS NOT NULL LIMIT 10` — resolved differs from raw
6. `SELECT distance_km, bearing FROM ships WHERE latitude IS NOT NULL LIMIT 5` — non-null after a position update
7. `/events` page shows no bare MMSI fallbacks for named ships
8. `/` index page loads without calling `distance_info()` in the hot loop
9. `EXPLAIN QUERY PLAN` on `get_ships_in_range()` shows SQL-level distance filter, not full table scan to Python

---

## Key Decisions

- AIS-sourced `imo`/`callsign` go on the `ships` table (raw AIS data). The `enrichment` table keeps its scraped copies; display logic already prefers enrichment over ships — no change needed there.
- `destination_resolved` computed at **write time** (upsert), not render time. Avoids repeated lazy-loads of `ais_destination_resolver` database on every ticker cycle.
- `distance_km`/`bearing` refreshed on every position update — stale values between updates are acceptable.
- ETA stored as a plain string because AIS ETA encodes only month/day/hour/minute without a year; avoiding year-inference complexity.
- Ship dimensions stored as integers (meters), matching AIS encoding; `None` when the sentinel value `0` is received.
- `ship_type_label` uses title-case consistently, resolving the current inconsistency between `web_service.py` and `ticker_content.py`.
- **Out of scope:** `epfd` field (low display value), nearby_cities caching (geonamescache is fast), system uptime/service state (intentionally live).

---

## Files to Touch

| File | Changes |
|------|---------|
| `ships_ahoy/db.py` | Migrations, `upsert_ship`, `write_event`, new `update_ship_spatial`, `get_ships_in_range` SQL |
| `ships_ahoy/ship_tracker.py` | `ShipInfo` dataclass, `ShipTracker.update()` |
| `ships_ahoy/distance.py` | New canonical `ship_type_label()` function |
| `services/ais_service.py` | Call `update_ship_spatial`; pass name to `write_event` |
| `services/web_service.py` | Remove computed fields in `index()`, `ship_detail()`, `events()` |
| `ships_ahoy/ticker_content.py` | `_extract_facts()`, `build_playlist()` |
| `ships_ahoy/destination.py` | No changes needed (called from upsert path, same API) |
| `ships_ahoy/events.py` | No changes needed (write_event call sites are in ais_service) |
