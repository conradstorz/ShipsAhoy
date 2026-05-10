# Ticker Refactor Design

**Date:** 2026-05-09
**Status:** Approved

## Problem

The existing ticker service has two distinct failures:

1. **Wrong content model.** The ticker is event-driven — it only scrolls a message when an ARRIVED, DEPARTED, STATUS_CHANGE, or ENRICHED event fires, then shows a static "N ships nearby" idle message otherwise. The desired behavior is a continuous information display cycling through detailed prose about every ship currently in range.

2. **Broken preview.** The web portal's `/ticker` preview shows no scrolling animation. Root cause: `StubMatrixDriver.scroll_text()` returns immediately (no sleep), so `display_state` flips from `scroll` back to `static` in microseconds — faster than the preview's 250 ms poll interval. The preview nearly always sees the static state.

## Chosen Approach

**Continuous cycle, no events.** The event table is retained for the web portal's audit log (still written by `ais_service`) but no longer drives the LED display. The ticker service generates a content playlist on each cycle from the live DB state.

## Content Model

### Ship chunks

For each in-range ship the ticker generates an ordered sequence of prose sentences. Each sentence includes the ship's name. Sentences for unavailable data are skipped — no "unknown" placeholders.

Order and templates:

| # | Condition | Template |
|---|-----------|----------|
| 1 | always (if name known) | `"{NAME} is a {TYPE} flying the {FLAG} flag"` |
| 2 | speed and heading known | `"{NAME} is traveling at {SPEED} knots heading {DIRECTION}"` |
| 3 | home location configured | `"{NAME} is {DISTANCE} km away, to the {BEARING}"` |
| 4 | status noteworthy (not "underway") | `"{NAME} is currently {STATUS}"` |
| 5 | destination set in AIS | `"{NAME} is bound for {DESTINATION}"` |
| 6 | always | `"{NAME} has visited this area {N} times"` / `"This is {NAME}'s first visit"` |
| 7 | enriched, length known | `"{NAME} is {LENGTH} meters long, built in {YEAR}"` |
| 8 | enriched, owner known | `"{NAME} is operated by {OWNER}"` |

Ships are ordered closest-first. The full cycle restarts from a fresh DB query after all ships have been shown.

### Idle pool

When no ships are within the configured distance, the display shows:

1. Fixed lead-in: `"No ships in range"`
2. All active quips and location facts, shuffled randomly
3. Reshuffled on every idle loop iteration

Idle content is stored in a new `quips` DB table. The web portal provides a CRUD interface.

## Database Changes

### New table: `quips`

```sql
CREATE TABLE IF NOT EXISTS quips (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    category   TEXT NOT NULL CHECK(category IN ('quip', 'location')),
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

No changes to existing tables. No migration needed for existing data.

## Module Structure

### New: `ships_ahoy/ticker_content.py`

Owns all content generation logic. No I/O except DB reads. Fully testable in isolation.

**Public API:**

```python
def build_ship_chunks(ship_row, enrichment_row, distance_km, bearing_label) -> list[str]:
    """Return ordered prose chunks for one ship. Skips unavailable fields."""

def get_in_range_ships_with_distance(conn, cfg) -> list[tuple[Row, Row | None, float, str]]:
    """Return (ship_row, enrichment_row, distance_km, bearing_label) for all
    in-range ships, sorted closest-first."""

def build_idle_chunks(conn) -> list[str]:
    """Return shuffled active quips + location facts, preceded by 'No ships in range'."""

def build_playlist(conn, cfg) -> list[str]:
    """Return the full scroll playlist for one cycle.
    Ships playlist if any in range, else idle playlist."""
```

### Modified: `services/ticker_service.py`

Main loop simplified to:

```python
while True:
    chunks = build_playlist(conn, cfg)
    for text in chunks:
        driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
```

Removed: `get_pending_events`, `mark_event_displayed`, `batch_mark_events_displayed`,
`_handle_overflow`, `_display_event`, `_show_idle`, overflow constants.

`display_state` writes removed. Nothing reads them in the new design; the table can be dropped in a future cleanup.

### Modified: `services/web_service.py`

**Preview SSE rewrite** — cuts `display_state` out of the preview pipeline:

1. SSE generator calls `build_playlist(conn, cfg)` to get chunks
2. For each chunk: calls `preview.scroll_text(text, speed)`, calculates duration
   (`pixel_width / speed_px_per_sec`), runs 30 FPS frame loop for that duration
3. Advances to next chunk when duration elapses; rebuilds playlist when cycle completes

**New route: `/quips`**

- `GET /quips` — renders list of all quips with add form
- `POST /quips` — add new quip (`text`, `category` fields)
- `POST /quips/<id>/toggle` — toggle active/inactive
- `POST /quips/<id>/delete` — delete quip

### Modified: `ships_ahoy/db.py`

New functions:

```python
def get_active_quips(conn) -> list[Row]: ...
def get_all_quips(conn) -> list[Row]: ...
def add_quip(conn, text: str, category: str) -> int: ...
def toggle_quip(conn, quip_id: int) -> None: ...
def delete_quip(conn, quip_id: int) -> None: ...
```

`init_db()` updated to create the `quips` table.

## What Is Not Changing

- `ais_service.py` — event detection and writing unchanged
- `enrichment_service.py` — unchanged
- `renderer.py`, `esp32_protocol.py`, `matrix_driver.py` — unchanged
- Events table and web portal event log — unchanged
- All existing settings (distance, scroll speed, home location) — unchanged

## Testing

- `test_ticker_content.py` — unit tests for each chunk builder function (mock ship/enrichment rows), playlist ordering, idle shuffle, empty-field skipping
- `test_ticker_service.py` — update to stub `build_playlist`, verify driver called for each chunk
- `test_web_service.py` — add tests for `/quips` CRUD routes
- `test_db.py` — add quips table CRUD tests
