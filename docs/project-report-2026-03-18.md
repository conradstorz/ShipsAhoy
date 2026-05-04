# ShipsAhoy — Project Report
**Date:** 2026-03-18

---

## Overview

ShipsAhoy is a real-time ship tracking system built around RTL-SDR hardware and AIS (Automatic Identification System) radio broadcasts. It ingests live maritime traffic over a USB dongle, decodes NMEA messages, stores ship positions and events in a SQLite database, enriches ship records via web scraping, and displays activity on an LED matrix ticker driven by an ESP32 microcontroller. A Flask web UI provides a browser-based view of tracked ships, events, and settings.

The project was started on 2026-03-07 and has 56 commits across 11 days of development.

---

## Repository Structure

```
ShipsAhoy/
├── main.py                        # CLI entry point (legacy terminal display)
├── services/                      # Long-running daemon processes
│   ├── ais_service.py             # AIS message ingest loop
│   ├── enrichment_service.py      # Web scraper for ship metadata
│   ├── ticker_service.py          # LED matrix display driver
│   └── web_service.py             # Flask web UI + REST API
├── ships_ahoy/                    # Core library
│   ├── ais_receiver.py            # TCP/UDP NMEA stream decoder
│   ├── config.py                  # Settings model backed by DB
│   ├── console_preview.py         # Terminal pixel preview
│   ├── db.py                      # SQLite schema + all DB queries
│   ├── display.py                 # Terminal ship table renderer
│   ├── distance.py                # Haversine distance calculations
│   ├── esp32_protocol.py          # Serial command protocol for ESP32
│   ├── events.py                  # EventType enum + event helpers
│   ├── matrix_driver.py           # LED matrix hardware abstraction
│   ├── renderer.py                # Pixel-level text renderer
│   ├── service_utils.py           # Shared service helpers
│   └── ship_tracker.py            # ShipInfo dataclass + tracker registry
├── tests/                         # 14 test files, 268 tests
└── docs/                          # Specs, plans, guides
```

---

## Source File Inventory

### Services (`services/`)

| File | Lines | Functions | Classes | Description |
|---|---|---|---|---|
| `ais_service.py` | 178 | 5 | 0 | AIS ingest: decode messages, write ship/event rows, stale sweep |
| `enrichment_service.py` | 273 | 8 | 0 | Scrape ship metadata from ShipXplorer, MarineTraffic, ITU; download photos |
| `ticker_service.py` | 162 | 5 | 0 | Display events on LED matrix; overflow and idle handling |
| `web_service.py` | 300 | 12 | 0 | Flask routes: index, ship detail, events, settings, ticker preview SSE |

### Core Library (`ships_ahoy/`)

| File | Lines | Functions | Classes | Description |
|---|---|---|---|---|
| `db.py` | 452 | 25 | 0 | Schema init, 6 indexes, all CRUD queries across 6 tables |
| `ship_tracker.py` | 240 | 7 | 2 | `ShipInfo` dataclass, `ShipTracker` registry keyed by MMSI |
| `matrix_driver.py` | 249 | 24 | 5 | `MatrixDriver`, `PreviewDriver`, ESP32 serial driver abstraction |
| `renderer.py` | 216 | 3 | 1 | Pixel-level font rendering for LED matrix frames |
| `events.py` | 141 | 3 | 1 | `EventType` StrEnum (ARRIVED, DEPARTED, STATUS_CHANGE, ENRICHED) |
| `ais_receiver.py` | 86 | 2 | 1 | TCP/UDP NMEA stream → decoded pyais messages (generator) |
| `config.py` | 80 | 9 | 1 | `Config` dataclass: distance_km, home_lat/lon, baud rate, etc. |
| `console_preview.py` | 109 | 5 | 0 | ANSI terminal preview of LED matrix frame |
| `display.py` | 101 | 4 | 0 | `rich`-based terminal table of live ships |
| `distance.py` | 81 | 5 | 0 | Haversine formula + range filter helpers |
| `esp32_protocol.py` | 98 | 3 | 0 | Serial framing protocol: scroll, static, frame, clear commands |
| `service_utils.py` | 15 | 1 | 0 | Shared `get_db_path()` helper |

### Entry Point

| File | Lines | Functions | Classes | Description |
|---|---|---|---|---|
| `main.py` | 121 | 2 | 0 | CLI argument parser + legacy terminal display loop |

---

## Project Totals

| Metric | Count |
|---|---|
| Source files (excl. tests, `__init__.py`) | 17 |
| Total lines (source) | ~2,906 |
| Total lines (tests) | ~2,153 |
| Functions (source) | ~99 |
| Classes (source) | 11 |
| Test files | 14 |
| Total tests | 268 |
| Git commits | 56 |
| Development span | 11 days (2026-03-07 to 2026-03-18) |

---

## Test Coverage

### Test Files

| File | Tests | Coverage Area |
|---|---|---|
| `test_db.py` | 61 | All DB query functions + 6 index existence checks |
| `test_display.py` | 31 | Terminal table rendering |
| `test_ship_tracker.py` | 39 | `ShipTracker` update logic, sentinel filtering |
| `test_config.py` | 15 | `Config` read/write from settings table |
| `test_distance.py` | 15 | Haversine math, range filter |
| `test_matrix_driver.py` | 24 | Driver selection, ESP32 serial protocol |
| `test_events.py` | 14 | Event write/read helpers |
| `test_esp32_protocol.py` | 12 | Serial frame encoding |
| `test_enrichment_service.py` | 12 | Scrapers, `_enrich_ship` fallback chain, `_process_one_ship` |
| `test_web_service.py` | 10 | Flask routes: index, ship detail, events, settings |
| `test_ais_receiver.py` | 10 | NMEA stream parsing |
| `test_ticker_service.py` | 8 | `_display_event`, `_show_idle`, `_handle_overflow` |
| `test_renderer.py` | 8 | Pixel font rendering |
| `test_ais_service.py` | 9 | `_process_message`, `_run_stale_sweep`, `_connect_with_backoff` |

---

## Database Schema

6 tables, all managed in `ships_ahoy/db.py`:

| Table | Key Columns | Purpose |
|---|---|---|
| `ships` | mmsi, name, lat, lon, status, enriched, last_seen | Core ship registry |
| `events` | mmsi, event_type, detail, created_at, displayed_at | ARRIVED/DEPARTED/STATUS_CHANGE/ENRICHED log |
| `ship_visits` | mmsi, arrived_at, departed_at | Visit open/close tracking |
| `enrichment` | mmsi, vessel_name, flag, imo, call_sign, photo_path | Scraped metadata |
| `settings` | key, value | User-configurable options (home_lat, distance_km, etc.) |
| `schema_version` | version | Migration version tracking |

### Indexes

6 `CREATE INDEX IF NOT EXISTS` statements added to `init_db()`:

| Index | Table | Columns | Type |
|---|---|---|---|
| `idx_ships_last_seen` | ships | last_seen | Standard |
| `idx_ships_enriched` | ships | enriched | Standard |
| `idx_ships_position` | ships | latitude, longitude | Partial (NOT NULL) |
| `idx_events_pending` | events | displayed_at, created_at | Partial (displayed_at IS NULL) |
| `idx_events_recent` | events | created_at | Standard |
| `idx_visits_mmsi` | ship_visits | mmsi | Standard |

---

## Dependencies

5 runtime packages (`requirements.txt`):

| Package | Version | Use |
|---|---|---|
| `pyais` | >=2.8.0 | AIS NMEA message decoding |
| `flask` | >=3.0 | Web UI and SSE ticker preview |
| `requests` | >=2.31 | HTTP scraping for ship enrichment |
| `beautifulsoup4` | >=4.12 | HTML parsing for scrapers |
| `pyserial` | >=3.5 | ESP32 serial communication |

---

## Architecture

Four independent daemon processes share a single SQLite database (WAL mode):

```
RTL-SDR hardware
    → rtl_ais (system tool)
    → TCP/UDP NMEA stream
    → ais_service          writes ships, events, ship_visits rows
    → enrichment_service   reads unenriched ships; scrapes; writes enrichment rows
    → ticker_service       reads pending events; drives ESP32 LED matrix via serial
    → web_service          Flask app; reads all tables; serves browser UI + SSE preview
```

The ESP32 microcontroller receives scroll/static/frame/clear commands over serial using a custom length-prefixed binary protocol (`esp32_protocol.py`), and drives a 320×8 RGB LED matrix panel.
