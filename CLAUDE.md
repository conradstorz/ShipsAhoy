# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Install dependencies:**
```bash
uv sync
```

**Run tests:**
```bash
uv run pytest tests/ -v
```

**Run a single test file:**
```bash
uv run pytest tests/test_ship_tracker.py -v
```

**Preview LED matrix output in terminal (no hardware needed):**
```bash
uv run python -m ships_ahoy.console_preview --text "Hello" --speed 40
```

**Run individual services directly (each requires rtl_ais and SQLite DB):**
```bash
uv run python services/ais_service.py
uv run python services/enrichment_service.py
uv run python services/ticker_service.py
uv run python services/web_service.py
```

**Legacy basic terminal display** (requires `rtl_ais` running first):
```bash
# Terminal 1:
rtl_ais -n -T -p 0 -d 0 2>/dev/null
# Terminal 2:
uv run python main.py [--host HOST] [--port PORT] [--udp] [--refresh SECS] [--verbose]
```

## Architecture

ShipsAhoy is a multi-service maritime AIS tracking system. AIS messages are received from an RTL-SDR dongle via the external `rtl_ais` tool and processed into a SQLite database shared by four independent services.

**Data flow:**
```
RTL-SDR hardware → rtl_ais (system tool) → TCP/UDP NMEA stream
  → AISReceiver (ships_ahoy/ais_receiver.py)     [decodes via pyais]
  → ShipTracker (ships_ahoy/ship_tracker.py)     [in-memory registry, keyed by MMSI]
  → SQLite DB (ships_ahoy/db.py)                 [WAL mode for concurrent access]
  → Ticker/Web/Enrichment services               [read from DB independently]
```

### Four Services

Each runs as an independent process (intended as systemd services) sharing the same SQLite DB via WAL mode:

| Service | File | Responsibility |
|---------|------|----------------|
| AIS | `services/ais_service.py` | Decodes AIS messages, upserts ships, detects and writes events |
| Enrichment | `services/enrichment_service.py` | Scrapes ship details from public maritime sites |
| Ticker | `services/ticker_service.py` | Drives physical LED matrix display |
| Web | `services/web_service.py` | Flask portal for ship browsing and settings |

### Database Schema (ships_ahoy/db.py)

Six tables, all opened with WAL mode:

- **ships** — primary ship state (MMSI PK, position, identity, first/last seen, visit count)
- **events** — audit log of ARRIVED / DEPARTED / STATUS_CHANGE / ENRICHED events with `displayed_at` tracking
- **enrichment** — scraped vessel details (IMO, call sign, dimensions, photo path, fetch attempts)
- **settings** — key-value config; web portal writes here, `Config` class reads live each access
- **ship_visits** — arrival/departure pairs per MMSI for multi-visit history
- **display_state** — single row (id=1) holding current LED display content

### Key Classes

**`ShipTracker`** (`ships_ahoy/ship_tracker.py`): In-memory dict of `ShipInfo` dataclasses keyed by MMSI. `update(msg)` processes any decoded AIS message and returns the updated `ShipInfo`. Filters AIS sentinel values (91° lat, 181° lon, 102.3 kts speed, 511 heading, 360° course) — fields stay `None` rather than showing bogus data. Derives country flag from first 3 digits of MMSI (Maritime ID lookup).

**`Config`** (`ships_ahoy/config.py`): Typed wrapper over the settings DB table. Reads on every property access — no caching — so web portal changes propagate to services immediately without restart.

**`EventType`** (`ships_ahoy/events.py`): Enum of ARRIVED / DEPARTED / STATUS_CHANGE / ENRICHED. `detect_events(old_ship, new_ship)` compares snapshots and returns triggered events. `format_ticker_message()` produces compact LED display strings.

### LED Matrix Display Stack

Three rendering layers with clean separation:

1. **`renderer.py`** — Pure data: text → PixelGrid (`list[list[RGB]]`) using a 5×8 bitmap font. `scroll_frame()` slices the grid at a given offset.
2. **`console_preview.py`** — Renders pixel grid in terminal via ANSI RGB + Unicode half-blocks (▀/▄, 2 LED rows per terminal line). Runnable standalone.
3. **`matrix_driver.py`** — Abstract `MatrixDriver` with `StubMatrixDriver` (stdout), `RGBMatrixDriver` (rpi-rgb-led-matrix, Pi only), `PreviewDriver` (web SSE), and `ESP32Driver` (UART at 921600 baud). Driver selection is automatic with silent fallback to stub.

**ESP32 wire protocol** (`esp32_protocol.py`): `[0xAA][CMD][LEN_HI][LEN_LO][PAYLOAD][CRC8]`. CRC8 uses polynomial 0x31. Sprite escapes: `\x1E + ID` (⚓=0x01, 🚢=0x02, etc.). Best-effort delivery — NACK/timeout returns normally.

### Design Decisions

- **No async/await.** Concurrency is achieved by process isolation (four services) + SQLite WAL mode. Each service runs a blocking polling loop.
- **AIS service reconnection**: exponential backoff from 1 s up to 60 s cap.
- **Distance filtering**: only ships within `distance_km` of configured home location write events. If home is unset, all ships trigger events (with a warning logged).
- **Enrichment retries**: scraping stops after `enrichment_max_attempts` consecutive failures. Sources tried in order: ShipXplorer → MyShipTracking → MarineTraffic → ITU MMSI form.
- **Ticker overflow**: if >10 events are pending and the oldest is >5 min old, the ticker flushes them all without displaying (prevents queue buildup while service is paused).
- **Atomic multi-step DB writes**: e.g., `mark_ship_departed()` writes the DEPARTED event and closes the visit in a single transaction.
- **No authentication on web portal (intentional)**: `web_service.py` binds to `0.0.0.0` with no auth or CSRF protection. This is a deliberate trade-off for a home LAN device. Do not add auth complexity unless the device will be port-forwarded to the internet.

## External Dependencies

- `rtl_ais`: system-level tool (not a Python package), must be running before `ais_service.py` connects. Tests mock the network layer.
- `rpi-rgb-led-matrix`: optional Pi-only library; if absent, ticker falls back to `StubMatrixDriver`.

## Licensing

Dual-licensed: AGPL-3.0 for open-source use, commercial license available separately. See `LICENSE-COMMERCIAL.md`.
