# ShipsAhoy — LED Ticker & Full System Design

**Date:** 2026-03-16
**Status:** Approved

---

## Overview

ShipsAhoy is expanded from a terminal-display proof-of-concept into a full headless system running permanently on a Raspberry Pi. It receives AIS ship broadcasts via RTL-SDR dongle + rtl_ais tool, persists ship data and event history in SQLite, enriches ships with data scraped from free internet sources, scrolls event notices on a HUB75 LED matrix ticker display, and exposes a web portal for browsing ships and adjusting settings.

---

## Hardware Target

- Raspberry Pi (any model with GPIO)
- RTL-SDR v3 dongle + marine VHF antenna
- 5× HUB75 64×32 LED matrix panels chained horizontally → 320×32 pixel canvas
- Driven by `rpi-rgb-led-matrix` (hzeller) C++ library with Python bindings

---

## Architecture

Four independent Python services share one SQLite database file (`ships.db`). All services are managed by systemd with `Restart=always`.

```
┌─────────────────────────────────────────────────────┐
│                  ships.db (SQLite)                  │
│    ships | events | enrichment | settings           │
└──────────┬──────────┬──────────┬───────────┬────────┘
           │          │          │           │
    ┌──────▼───┐ ┌────▼────┐ ┌──▼──────┐ ┌─▼───────┐
    │  ais-    │ │ ticker  │ │ enrich  │ │  web    │
    │ receiver │ │ service │ │ service │ │ portal  │
    │          │ │ (HUB75) │ │         │ │ (Flask) │
    └──────────┘ └─────────┘ └─────────┘ └─────────┘
```

Inter-process communication is via SQLite polling — no message broker required. Services poll at their own cadence (1–5 seconds). SQLite is opened with WAL journal mode (`PRAGMA journal_mode=WAL`) by `init_db()` to prevent `SQLITE_BUSY` errors with four concurrent processes.

---

## File Layout

```
ships_ahoy/           # shared library (imported by all services)
    __init__.py
    ais_receiver.py   # existing — unchanged
    ship_tracker.py   # existing — MODIFIED: ShipInfo extended with destination and flag fields
    display.py        # existing — terminal display, kept for dev/debug
    db.py             # NEW — all SQLite access
    config.py         # NEW — settings table wrapper
    events.py         # NEW — event types, detection, ticker formatting
    distance.py       # NEW — haversine, bearing, noteworthy check
    matrix_driver.py  # NEW — MatrixDriver interface + stub

services/
    ais_service.py        # hardened AIS receiver, replaces main.py
    ticker_service.py     # HUB75 scrolling ticker
    enrichment_service.py # free-source web scraper
    web_service.py        # Flask web portal

static/
    photos/           # cached ship photos, named <mmsi>.jpg

templates/            # Flask HTML templates
    index.html
    ship.html
    events.html
    settings.html

systemd/
    ships-ahoy-ais.service
    ships-ahoy-ticker.service
    ships-ahoy-enrichment.service
    ships-ahoy-web.service
    ships-ahoy.target

tests/
    test_ais_receiver.py    # existing
    test_ship_tracker.py    # existing
    test_display.py         # existing
    test_db.py              # NEW
    test_distance.py        # NEW
    test_events.py          # NEW
    test_matrix_driver.py   # NEW

main.py               # kept for manual terminal use / dev testing
```

---

## Database Schema

### `ships`
| Column | Type | Notes |
|---|---|---|
| mmsi | INTEGER PK | unique ship identifier |
| name | TEXT | |
| ship_type | INTEGER | AIS numeric code |
| flag | TEXT | from AIS or enrichment (enrichment takes priority when non-null) |
| latitude | REAL | last known |
| longitude | REAL | last known |
| speed | REAL | knots |
| heading | REAL | degrees |
| course | REAL | degrees over ground |
| status | INTEGER | AIS nav status code |
| destination | TEXT | from AIS type-5 messages, updated by ais_service |
| first_seen | DATETIME | |
| last_seen | DATETIME | |
| visit_count | INTEGER | number of distinct visits |
| enriched | BOOLEAN | enrichment attempted? |

Note: `destination` lives on `ships` (not `enrichment`) because it is reported live via AIS type-5 messages and changes voyage-by-voyage.

Note: `ShipInfo` in `ship_tracker.py` will be extended with two new optional fields: `destination: Optional[str] = None` and `flag: Optional[str] = None`. These are populated by `ais_receiver.py` from AIS message types 5 and 24. `upsert_ship()` writes them to the ships table directly from the `ShipInfo` object.

### `events`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| mmsi | INTEGER | |
| event_type | TEXT | ARRIVED / DEPARTED / STATUS_CHANGE / ENRICHED |
| detail | TEXT | human-readable ticker string |
| created_at | DATETIME | |
| displayed_at | DATETIME | NULL until ticker shows it |

### `enrichment`
| Column | Type | Notes |
|---|---|---|
| mmsi | INTEGER PK | |
| vessel_name | TEXT | |
| imo | TEXT | International Maritime Org number |
| call_sign | TEXT | |
| flag | TEXT | takes priority over ships.flag when non-null |
| ship_type_label | TEXT | human label (e.g. "Bulk Carrier") |
| length_m | REAL | |
| build_year | INTEGER | |
| owner | TEXT | |
| photo_url | TEXT | source URL |
| photo_path | TEXT | local file path under static/photos/ |
| source | TEXT | which site provided data |
| fetched_at | DATETIME | |
| fetch_attempts | INTEGER | stops retrying after 3 |

### `settings`
| Column | Type | Notes |
|---|---|---|
| key | TEXT PK | |
| value | TEXT | |

Default keys and values:

| Key | Default | Notes |
|---|---|---|
| home_lat | None | Required — services log a warning and skip distance checks if unset |
| home_lon | None | Required — same |
| distance_km | 50 | Ships within this range are noteworthy |
| scroll_speed_px_per_sec | 40 | Ticker scroll rate |
| stale_ship_hours | 1 | Hours before absent ship fires DEPARTED event |
| enrichment_delay_sec | 10 | Pause between scrape requests |
| enrichment_max_attempts | 3 | Stops retrying after this many failures |

If `home_lat` or `home_lon` is None/unset, `is_noteworthy()` returns `True` for all ships (fail-open) and a warning is logged. The settings page prompts the user to set their location on first visit.

### `ship_visits`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| mmsi | INTEGER | |
| arrived_at | DATETIME | |
| departed_at | DATETIME | NULL while ship still present |

---

## Shared Library Modules

### `ships_ahoy/db.py`

All SQLite access for all services. `init_db()` enables WAL mode and creates all tables.

**Connection contract:** Each service opens one connection at startup via `init_db()` and holds it for the process lifetime. `check_same_thread=False` is not needed (one thread per service). WAL mode allows concurrent reads from multiple processes with one writer at a time.

**Write functions:**
- `init_db(path: str) -> sqlite3.Connection` — creates tables, enables WAL, returns connection
- `upsert_ship(conn, ship: ShipInfo) -> None` — inserts or updates the ships row; imports `ShipInfo` from `ships_ahoy.ship_tracker`
- `save_enrichment(conn, mmsi: int, data: dict) -> None` — writes enrichment row, sets `ships.enriched = TRUE`
- `write_event(conn, mmsi: int, event_type: str, detail: str) -> None`
- `record_visit(conn, mmsi: int) -> None` — inserts open ship_visits row (departed_at NULL)
- `close_visit(conn, mmsi: int) -> None` — sets departed_at on most recent open visit for mmsi
- `mark_event_displayed(conn, event_id: int) -> None`
- `mark_ship_departed(conn, mmsi: int) -> None` — writes DEPARTED event, calls close_visit(), does NOT delete the ship row

**Read functions:**
- `get_ship(conn, mmsi: int) -> sqlite3.Row | None`
- `get_enrichment(conn, mmsi: int) -> sqlite3.Row | None`
- `get_unenriched_ships(conn, max_attempts: int) -> list[int]` — MMSIs where `enriched = FALSE` and `fetch_attempts < max_attempts`
- `get_pending_events(conn) -> list[sqlite3.Row]` — events where `displayed_at IS NULL`, ordered by created_at
- `get_ships_in_range(conn, home_lat: float, home_lon: float, km: float) -> list[sqlite3.Row]`
- `get_visit_history(conn, mmsi: int) -> list[sqlite3.Row]` — all ship_visits rows for mmsi, newest first
- `get_recent_events(conn, limit: int = 50) -> list[sqlite3.Row]`

**Coupling note:** `db.py` imports `ShipInfo` from `ships_ahoy.ship_tracker`. This is intentional and acceptable — `db.py` is the persistence layer for the domain model. `ship_tracker.py` has no imports from `db.py`, so there is no circular dependency.

### `ships_ahoy/config.py`
- `Config(conn: sqlite3.Connection)` — wraps settings table
- `Config.get(key: str, default: str | None = None) -> str | None` — reads from DB each call
- `Config.set(key: str, value: str) -> None`
- `Config.home_location -> tuple[float, float] | None` — returns None if either coord unset
- `Config.distance_km -> float`
- `Config.stale_ship_hours -> float`
- `Config.scroll_speed -> float`
- `Config.enrichment_delay_sec -> float`
- `Config.enrichment_max_attempts -> int`

Re-reads DB on every property access — no restart needed for setting changes.

### `ships_ahoy/events.py`
- `EventType` — string constants: `ARRIVED`, `DEPARTED`, `STATUS_CHANGE`, `ENRICHED`
- `detect_events(old_ship: ShipInfo, new_ship: ShipInfo) -> list[tuple[str, str]]` — compares two `ShipInfo` objects, returns list of `(event_type, detail)` pairs. Both parameters are `ShipInfo` dataclass instances from `ships_ahoy.ship_tracker`. This function is NOT called for new ships — `ais_service.py` writes the ARRIVED event directly when a ship is first seen (there is no `old_ship` to compare against).
- `format_ticker_message(event_row: sqlite3.Row, ship_row: sqlite3.Row, enrichment_row: sqlite3.Row | None) -> str` — produces single-line display string e.g. `"⚓ CARGO 'ATLANTIC STAR' — underway — 2.3 km NE"`. `enrichment_row` may be None.

### `ships_ahoy/distance.py`
- `haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float`
- `bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float`
- `bearing_to_cardinal(degrees: float) -> str` — e.g. `"WSW"`
- `is_noteworthy(ship_lat: float, ship_lon: float, home_lat: float, home_lon: float, threshold_km: float) -> bool`

### `ships_ahoy/matrix_driver.py`

Defines the `MatrixDriver` interface and two implementations: real HUB75 and a no-op stub for non-Pi environments.

```
MatrixDriver (abstract base)
    scroll_text(text: str, speed_px_per_sec: float) -> None
    clear() -> None
    show_static(text: str, duration_sec: float) -> None

RGBMatrixDriver(MatrixDriver)
    # Real implementation using rpi-rgb-led-matrix Python bindings
    # Panel config: 5 chained 64x32 panels, total 320x32

StubMatrixDriver(MatrixDriver)
    # No-op implementation for dev/test on non-Pi hardware
    # Logs text to stdout instead of driving hardware
```

`ticker_service.py` imports `MatrixDriver` only. At startup it attempts to import `rpi-rgb-led-matrix`; if unavailable it falls back to `StubMatrixDriver` automatically.

---

## Services

### `services/ais_service.py`
- Connects to rtl_ais via `AISReceiver` (existing)
- Reconnect loop: exponential backoff 1s → 2s → 4s → … capped at 60s, retries forever
- On each message: call `upsert_ship()`, fetch previous ship state with `get_ship()` before upsert to compare, call `detect_events(old, new)`, write any resulting events via `write_event()`
- New ships: also call `record_visit()` and write `ARRIVED` event
- Stale-ship sweep: every 5 minutes, query ships where `last_seen < now - stale_ship_hours`; for each, call `mark_ship_departed()` (which writes DEPARTED event + closes visit)
- Only writes ARRIVED/DEPARTED/STATUS_CHANGE events for ships within `distance_km` of home
- Logs warning if home location is unset; processes all ships regardless

### `services/enrichment_service.py`
- Polls `get_unenriched_ships()` in a loop
- Sleeps `enrichment_delay_sec` between each request
- Scrape targets (free, no login required):
  - `https://www.shipxplorer.com/vessel/<mmsi>` — vessel details + photo
  - `https://www.marinetraffic.com/en/ais/details/ships/mmsi:<mmsi>` — fallback (may block)
  - `https://www.itu.int/mmsapp/ShipSearch.do` — ITU MMSI lookup (form POST)
- HTTP client: `requests` + `BeautifulSoup` (html.parser)
- Fallback strategy: tries each source in order; stops on first success. If all fail, increments `fetch_attempts`. Once `fetch_attempts >= enrichment_max_attempts`, ship is permanently skipped.
- Downloads first available photo to `static/photos/<mmsi>.jpg`
- Writes `ENRICHED` event when new data is successfully found

### `services/ticker_service.py`
- Opens DB connection, instantiates `MatrixDriver` (real or stub)
- Polls `get_pending_events()` every 2 seconds
- For each event: fetches `get_ship()` and `get_enrichment()`, calls `format_ticker_message()`, scrolls result via `MatrixDriver.scroll_text()`
- After scroll completes: calls `mark_event_displayed()`
- When queue empty: calls `MatrixDriver.show_static()` with idle message `"ShipsAhoy — N ships nearby"`
- Queue overflow handling: if more than 10 events are pending, events older than 5 minutes are skipped (marked displayed without scrolling) and a single summary message is scrolled instead: `"ShipsAhoy — N new events (queue flushed)"`. This prevents the ticker falling arbitrarily far behind during fleet arrivals.

### `services/web_service.py`
Flask app on port 5000:
- `GET /` — ship list sorted by last_seen, with distance and type
- `GET /ship/<mmsi>` — all ships row fields + enrichment row + visit history + photo (if exists)
- `GET /events` — `get_recent_events(limit=50)`
- `GET /settings` — renders form pre-populated from Config
- `POST /settings` — saves updated values via `Config.set()`, redirects to GET /settings
- `GET /static/photos/<filename>` — served by Flask

Flag display rule: show `enrichment.flag` when non-null, otherwise `ships.flag`.

---

## Operational Hardening

### Systemd Unit Files

All units run as user `pi` (or the configured deploy user). `WorkingDirectory` is the project root. `ExecStart` uses the `uv`-managed venv: `uv run python services/<service>.py`.

**`ships-ahoy-ais.service`:**
```
[Unit]
Description=ShipsAhoy AIS Receiver
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/ShipsAhoy
ExecStart=uv run python services/ais_service.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=ships-ahoy.target
```

**`ships-ahoy-ticker.service`**, **`ships-ahoy-enrichment.service`**, **`ships-ahoy-web.service`**: same pattern, different `ExecStart`. Ticker service adds `After=ships-ahoy-ais.service` as a startup ordering hint only (not `BindsTo=`) — the ticker can run independently once the DB exists, even if the AIS service is temporarily down.

**`ships-ahoy.target`:**
```
[Unit]
Description=ShipsAhoy All Services
Wants=ships-ahoy-ais.service ships-ahoy-ticker.service ships-ahoy-enrichment.service ships-ahoy-web.service

[Install]
WantedBy=multi-user.target
```

`systemctl enable ships-ahoy.target` starts everything on boot.

### Exception Handling
- Each service has a top-level exception handler in its main loop: logs the exception, sleeps 1 second, continues — no service dies on a single bad message or failed scrape
- `ais_service.py` reconnect loop is separate from the message-processing loop so a decode error does not trigger a reconnect

### Stale Ship Departure Sweep
The 5-minute sweep in `ais_service.py` queries for ships past `stale_ship_hours`. For each: calls `mark_ship_departed(conn, mmsi)` which atomically: writes a DEPARTED event to `events`, calls `close_visit()`, and does not delete the ships row (history preserved permanently).

---

## Testing

- `test_db.py` — uses SQLite `":memory:"`, tests all db.py functions including WAL mode setup
- `test_distance.py` — pure function unit tests with known lat/lon pairs and expected km/bearing results
- `test_events.py` — unit tests for `detect_events()` with ShipInfo pairs and `format_ticker_message()` with mock Row objects
- `test_matrix_driver.py` — tests `StubMatrixDriver` conforms to `MatrixDriver` interface
- Services not directly unit tested; all logic lives in imported modules that are tested
- `StubMatrixDriver` allows ticker logic to be exercised without Pi hardware

---

## Scaffolding Convention

Every new module and service is created with:
- Module-level docstring describing purpose
- All public function/method signatures with type hints
- `raise NotImplementedError` stubs (or `pass` for `__init__` and property stubs)
- Correct imports already wired (no placeholder import comments)

This ensures the architecture compiles and all imports resolve before any implementation begins.

---

## Web Scraping Notes

Free sources are inherently fragile. The enrichment service is designed to degrade gracefully:
- All scraping is wrapped in try/except; any HTTP or parse error increments `fetch_attempts` and moves on
- Sources are tried in order of reliability; the list can be extended without changing the service architecture
- A ship with `fetch_attempts >= max_attempts` is shown on the web portal with a "No enrichment data" notice
- The `fetched_at` timestamp allows future re-enrichment by resetting `enriched = FALSE` via an admin action
