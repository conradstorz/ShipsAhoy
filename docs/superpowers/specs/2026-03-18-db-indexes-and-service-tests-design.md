# DB Indexes & Service Integration Tests — Design

**Date:** 2026-03-18
**Status:** Approved

---

## Overview

Two independent improvements to the ShipsAhoy codebase:

1. **DB Indexes** — add six indexes to `ships_ahoy/db.py` to eliminate full-table scans on the most common queries.
2. **Service Integration Tests** — add test files for all four services (`ais_service`, `enrichment_service`, `ticker_service`, `web_service`), testing core logic functions against a real `:memory:` SQLite database with external I/O mocked.

---

## Part 1: Database Indexes

### Approach

Add `CREATE INDEX IF NOT EXISTS` statements to `init_db()` in `ships_ahoy/db.py`, immediately after the table CREATE statements. Using `IF NOT EXISTS` makes them safe to apply to existing databases.

### Indexes

| Name | Table | Columns | Type | Justification |
|---|---|---|---|---|
| `idx_ships_last_seen` | ships | last_seen | Standard | `get_all_ships` ORDER BY, `get_stale_mmsis` WHERE |
| `idx_ships_enriched` | ships | enriched | Standard | `get_unenriched_ships` WHERE enriched=FALSE |
| `idx_ships_position` | ships | latitude, longitude | Partial (`WHERE latitude IS NOT NULL AND longitude IS NOT NULL`) | `get_ships_in_range` WHERE clause |
| `idx_events_pending` | events | displayed_at, created_at | Partial (displayed_at IS NULL) | `get_pending_events` WHERE + ORDER BY |
| `idx_events_recent` | events | created_at | Standard | `get_recent_events` ORDER BY created_at DESC |
| `idx_visits_mmsi` | ship_visits | mmsi | Standard | JOIN in `get_stale_mmsis`, subquery in `close_visit` |

SQLite supports partial indexes (`CREATE INDEX ... WHERE condition`), used for `idx_ships_position` and `idx_events_pending` to keep index size minimal.

### Index Verification Tests

Add tests to `tests/test_db.py` asserting that each index exists by querying `sqlite_master`:

```python
def test_indexes_exist(conn):
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()}
    for idx in [
        "idx_ships_last_seen", "idx_ships_enriched", "idx_ships_position",
        "idx_events_pending", "idx_events_recent", "idx_visits_mmsi",
    ]:
        assert idx in names
```

---

## Part 2: Service Integration Tests

### Test Strategy

- **Real** `:memory:` SQLite DB via `init_db(":memory:")` — tests actual DB interactions
- **Real** service logic functions — `_process_message`, `_run_stale_sweep`, `_display_event`, `_handle_overflow`, `_show_idle`, scraper functions, web routes
- **Mocked** external I/O only: `AISReceiver`, `requests.get`/`requests.post`, `serial.Serial`, `time.sleep`
- **Style:** plain functions with pytest fixtures, consistent with existing test files

---

### ais_service — `tests/test_ais_service.py`

**Import pattern:** Import the module, then reference functions as `svc._process_message`, etc.
```python
import services.ais_service as svc
```

**`_tracker` reset:** Use a function-scoped fixture that replaces the module-level tracker before each test:
```python
@pytest.fixture(autouse=True)
def reset_tracker():
    from ships_ahoy.ship_tracker import ShipTracker
    svc._tracker = ShipTracker()
```

**`conn` fixture:** `init_db(":memory:")` with home location set to (51.5, 0.0):
```python
@pytest.fixture
def conn():
    c = init_db(":memory:")
    c.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    c.execute("UPDATE settings SET value='0.0' WHERE key='home_lon'")
    c.commit()
    return c
```

**`cfg` fixture:** `Config(conn)`.

**`time.sleep` mock target:** Patch `services.ais_service.time.sleep` (not `time.sleep` globally).

**Tests:**

| Test | Setup | What it verifies |
|---|---|---|
| `test_new_ship_writes_arrived_event` | Craft a mock AIS msg that tracker will accept; ship at lat=51.5, lon=0.0 | ARRIVED event in events table + open visit in ship_visits |
| `test_new_ship_outside_range_no_event` | Ship at lat=0.0, lon=0.0 (far from home) | No rows in events table |
| `test_status_change_writes_event` | Insert existing ship row with status=0; new msg has status=5 | STATUS_CHANGE event in events table |
| `test_no_home_location_treats_all_noteworthy` | home_lat/lon remain NULL in settings; ship at lat=0.0, lon=0.0 | ARRIVED event written despite distance |
| `test_message_returns_none_is_noop` | Patch `svc._tracker.update` to return None | No rows in events or ship_visits |
| `test_run_stale_sweep_marks_departed` | Insert ship with last_seen 2 hours ago; insert open ship_visit | DEPARTED event in events table |
| `test_run_stale_sweep_skips_fresh_ships` | Insert ship with last_seen=now; insert open ship_visit | No DEPARTED event |
| `test_connect_with_backoff_succeeds` | Patch `socket.create_connection` to succeed; patch `services.ais_service.AISReceiver` | Returns an AISReceiver instance |
| `test_connect_with_backoff_retries` | Patch `socket.create_connection` to raise once then succeed; patch `services.ais_service.time.sleep` | `time.sleep` called once |

**Crafting AIS messages for `_process_message`:** Use `unittest.mock.MagicMock()` to produce a decoded message object. `ShipTracker.update()` expects a pyais decoded message with attributes like `mmsi`, `lat`, `lon`, `status`, etc. The simplest approach is to mock `svc._tracker.update` directly to return a `ShipInfo` instance with controlled field values, rather than building real NMEA sentences.

---

### enrichment_service — `tests/test_enrichment_service.py`

**Import pattern:**
```python
import services.enrichment_service as svc
```

**Note on `_scrape_itu`:** Uses `requests.post`, not `requests.get`. Mock `requests.post` separately when testing this function.

**HTML fixtures:** Define minimal HTML strings as module-level constants in the test file.

**`_process_one_ship` refactor:** The main loop logic in `enrichment_service.py` is not testable as-is because it lives directly inside `main()`. Extract it into a helper function:
```python
def _process_one_ship(conn, mmsi: int, photos_dir: Path) -> None:
    """Enrich one ship: try scrapers, save result or increment attempts."""
    ...
```
This is a required code change to `services/enrichment_service.py` (extracted from the existing `for mmsi in mmsi_list` loop body). `main()` calls `_process_one_ship(conn, mmsi, photos_dir)`.

**Tests:**

| Test | Mock | What it verifies |
|---|---|---|
| `test_scrape_shipxplorer_parses_vessel_name` | `requests.get` → HTML with `<h1>MV Example</h1>` | result["vessel_name"] == "MV Example" |
| `test_scrape_shipxplorer_parses_table_fields` | `requests.get` → HTML with table rows for flag/imo/call/type/length/year | All fields parsed correctly |
| `test_scrape_shipxplorer_returns_none_on_http_error` | `requests.get` → `.raise_for_status()` raises `HTTPError` | Returns None |
| `test_scrape_marinetraffic_cloudflare_returns_none` | `requests.get` → body contains "cloudflare" | Returns None |
| `test_scrape_itu_parses_table_row` | `requests.post` → HTML table with one data row | vessel_name, call_sign, flag extracted |
| `test_enrich_ship_returns_first_success` | `_scrape_shipxplorer` patched to return dict | Result returned; `_scrape_marinetraffic` not called |
| `test_enrich_ship_falls_through_on_failure` | `_scrape_shipxplorer` raises; `_scrape_marinetraffic` returns None; `_scrape_itu` returns dict | Third result returned |
| `test_enrich_ship_all_fail_returns_none` | All three scrapers raise | Returns None |
| `test_download_photo_saves_file` | `requests.get` → streaming response, content-type=image/jpeg | File written to tmp_path |
| `test_download_photo_wrong_content_type_returns_none` | `requests.get` → content-type=text/html | Returns None; no file created |
| `test_process_one_ship_enriches_ship` | Unenriched ship in `:memory:` DB; `_enrich_ship` patched to return dict **without `photo_url`** (avoids triggering `_download_photo`) | `enrichment` row exists; ENRICHED event in events table; `ships.enriched=TRUE` |
| `test_process_one_ship_increments_attempts_on_failure` | Unenriched ship in `:memory:` DB; `_enrich_ship` patched to return None | `enrichment.fetch_attempts` == 1; no ENRICHED event |

---

### ticker_service — `tests/test_ticker_service.py`

Expand existing file. Import service functions:
```python
import importlib, sys
from unittest import mock
# Import lazily with matrix_driver mocked (same pattern as existing tests)
```

**`conn` fixture:** `init_db(":memory:")` with home location set.

**`cfg` fixture:** `Config(conn)`.

**`driver` fixture:** `MagicMock()` with `scroll_text`, `show_static`, `clear` as mock methods.

**Backdating events:** The overflow threshold check uses `e["created_at"] < cutoff` where cutoff is 5 minutes ago. Since `write_event` always uses `_now_iso()`, stale events must be inserted directly:
```python
conn.execute("INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
             (mmsi, "ARRIVED", "detail", "2020-01-01T00:00:00"))
conn.commit()
```

**Tests:**

| Test | Setup | What it verifies |
|---|---|---|
| `test_display_event_scrolls_and_marks_displayed` | Ship in DB; event in DB; enrichment absent | `driver.scroll_text` called once; event row has `displayed_at` set |
| `test_display_event_skips_missing_ship` | Event inserted directly (no ship row for that MMSI) | `driver.scroll_text` NOT called; event `displayed_at` set |
| `test_show_idle_with_home_uses_range_count` | home set in settings; 2 ships at lat=51.5, lon=0.0 | `driver.show_static` called with message containing "2" |
| `test_show_idle_without_home_uses_total_count` | home_lat/lon NULL; 3 ships in DB | `driver.show_static` called with message containing "3" |
| `test_handle_overflow_flushes_stale_events` | 12 events: 11 with backdated `created_at`, 1 recent | 11 events have `displayed_at` set; `driver.scroll_text` called with "flushed" in message |
| `test_handle_overflow_displays_oldest_when_no_stale` | 12 fresh events + ship row for events[0]["mmsi"] | `driver.scroll_text` called once (via `_display_event`); oldest event has `displayed_at` set |

---

### web_service — `tests/test_web_service.py`

Expand existing file. Modify the existing `client` fixture to also yield the DB connection, so tests can seed data:

```python
@pytest.fixture
def client(tmp_path):
    ...
    with ws.app.test_client() as c:
        yield c, ws._conn   # yield both client and connection
```

Update the two existing tests to unpack `(client, conn)` from the fixture, or add a separate `conn` fixture that re-uses `ws._conn`.

**Tests:**

| Test | Setup | What it verifies |
|---|---|---|
| `test_index_returns_200` | No ships needed | GET `/` → 200 |
| `test_index_shows_ship_name` | Insert ship via `upsert_ship(conn, ...)` | Ship name appears in response body HTML |
| `test_ship_detail_returns_200` | Insert ship via `upsert_ship` | GET `/ship/<mmsi>` → 200 |
| `test_ship_detail_404_for_unknown` | No ship for that MMSI | GET `/ship/9999999` → 404 |
| `test_events_returns_200` | No events needed | GET `/events` → 200 |
| `test_settings_get_returns_200` | No setup | GET `/settings` → 200 |
| `test_settings_post_saves_values` | POST `distance_km=25.0` | Redirects; `cfg.distance_km == 25.0` |
| `test_settings_post_ignores_invalid_float` | POST `distance_km=notanumber` | Redirects without crash; value unchanged |

---

## File Changes

| File | Change |
|---|---|
| `ships_ahoy/db.py` | Add 6 index statements to `init_db()` |
| `tests/test_db.py` | Add index existence test |
| `services/enrichment_service.py` | Extract `_process_one_ship(conn, mmsi, photos_dir)` helper from `main()` loop body |
| `tests/test_ais_service.py` | New file, 9 tests |
| `tests/test_enrichment_service.py` | New file, 12 tests |
| `tests/test_ticker_service.py` | Expand existing, add 6 tests |
| `tests/test_web_service.py` | Expand existing (modify fixture + add 8 tests) |

**Total new tests: ~42**

---

## Out of Scope

- AIS receiver reconnection stress tests
- Multi-process WAL concurrency tests
- End-to-end systemd service tests
- Template HTML correctness tests
