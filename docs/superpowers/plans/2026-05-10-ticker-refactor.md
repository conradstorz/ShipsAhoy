# Ticker Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the event-driven ticker with a continuous-cycle display of prose chunks about in-range ships, fix the broken web preview, and add an editable idle quips pool.

**Architecture:** A new `ships_ahoy/ticker_content.py` module owns all content generation (ship prose chunks, idle quips playlist, full cycle playlist). `ticker_service.py` is reduced to a thin driver loop that calls `build_playlist()` and scrolls each chunk. The web service preview SSE endpoint is rewritten to call `build_playlist()` directly instead of polling `display_state`, eliminating the timing race that caused static-only output.

**Tech Stack:** Python 3.11+, SQLite (WAL), Flask, pyais, loguru, uv/pytest

**Spec:** `docs/superpowers/specs/2026-05-09-ticker-refactor-design.md`

---

## File Map

| Action | Path |
|--------|------|
| Modify | `ships_ahoy/db.py` |
| Create | `ships_ahoy/ticker_content.py` |
| Rewrite | `services/ticker_service.py` |
| Modify | `services/web_service.py` |
| Create | `templates/quips.html` |
| Modify | `tests/test_db.py` |
| Create | `tests/test_ticker_content.py` |
| Rewrite | `tests/test_ticker_service.py` |
| Modify | `tests/test_web_service.py` |

---

## Task 1: quips table and CRUD functions

**Files:**
- Modify: `ships_ahoy/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Add failing tests to test_db.py**

Append to the existing imports at the top of `tests/test_db.py`:
```python
from ships_ahoy.db import (
    add_quip,
    get_all_quips,
    get_active_quips,
    toggle_quip,
    delete_quip,
)
```

Append to the end of `tests/test_db.py`:
```python
# --- quips table ---

def test_add_quip_returns_int_id(conn):
    qid = add_quip(conn, "Why don't sailors play cards?", "quip")
    assert isinstance(qid, int) and qid > 0


def test_get_all_quips_returns_all_rows(conn):
    add_quip(conn, "A quip", "quip")
    add_quip(conn, "A location fact", "location")
    rows = get_all_quips(conn)
    assert len(rows) == 2


def test_get_active_quips_excludes_inactive(conn):
    qid = add_quip(conn, "Inactive quip", "quip")
    add_quip(conn, "Active quip", "quip")
    toggle_quip(conn, qid)
    rows = get_active_quips(conn)
    assert len(rows) == 1
    assert rows[0]["text"] == "Active quip"


def test_toggle_quip_deactivates_then_reactivates(conn):
    qid = add_quip(conn, "Toggleable", "quip")
    toggle_quip(conn, qid)
    row = conn.execute("SELECT active FROM quips WHERE id=?", (qid,)).fetchone()
    assert row["active"] == 0
    toggle_quip(conn, qid)
    row = conn.execute("SELECT active FROM quips WHERE id=?", (qid,)).fetchone()
    assert row["active"] == 1


def test_delete_quip_removes_row(conn):
    qid = add_quip(conn, "To be deleted", "quip")
    delete_quip(conn, qid)
    assert get_all_quips(conn) == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_db.py::test_add_quip_returns_int_id -v
```
Expected: `ImportError: cannot import name 'add_quip'`

- [ ] **Step 3: Add `_CREATE_QUIPS` constant to `ships_ahoy/db.py`**

After the `_CREATE_DISPLAY_STATE` constant (around line 101), add:
```python
_CREATE_QUIPS = """
CREATE TABLE IF NOT EXISTS quips (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    category   TEXT NOT NULL CHECK(category IN ('quip', 'location')),
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""
```

- [ ] **Step 4: Call `_CREATE_QUIPS` inside `init_db()`**

In `init_db()`, after `conn.execute(_CREATE_DISPLAY_STATE)`, add:
```python
    conn.execute(_CREATE_QUIPS)
```

- [ ] **Step 5: Add five CRUD functions at the end of `ships_ahoy/db.py`**

```python
def get_all_quips(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all quips ordered by created_at descending."""
    return conn.execute(
        "SELECT * FROM quips ORDER BY created_at DESC"
    ).fetchall()


def get_active_quips(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return only active quips ordered by created_at descending."""
    return conn.execute(
        "SELECT * FROM quips WHERE active = 1 ORDER BY created_at DESC"
    ).fetchall()


def add_quip(conn: sqlite3.Connection, text: str, category: str) -> int:
    """Insert a new quip and return its id."""
    cur = conn.execute(
        "INSERT INTO quips (text, category) VALUES (?, ?)", (text, category)
    )
    conn.commit()
    return cur.lastrowid


def toggle_quip(conn: sqlite3.Connection, quip_id: int) -> None:
    """Flip the active flag for the given quip."""
    conn.execute(
        "UPDATE quips SET active = NOT active WHERE id = ?", (quip_id,)
    )
    conn.commit()


def delete_quip(conn: sqlite3.Connection, quip_id: int) -> None:
    """Delete the quip with the given id."""
    conn.execute("DELETE FROM quips WHERE id = ?", (quip_id,))
    conn.commit()
```

- [ ] **Step 6: Run tests to confirm they pass**

```
uv run pytest tests/test_db.py -v -k "quip"
```
Expected: 5 PASSED

- [ ] **Step 7: Run the full test suite to check for regressions**

```
uv run pytest tests/ -v
```
Expected: All previously passing tests still pass.

- [ ] **Step 8: Commit**

```
git add ships_ahoy/db.py tests/test_db.py
git commit -m "feat: add quips table and CRUD functions to db"
```

---

## Task 2: `ticker_content.py` — build_ship_chunks

**Files:**
- Create: `ships_ahoy/ticker_content.py`
- Create: `tests/test_ticker_content.py`

- [ ] **Step 1: Create the test file with build_ship_chunks tests**

Create `tests/test_ticker_content.py`:
```python
"""Tests for ships_ahoy.ticker_content."""
import pytest
from ships_ahoy.db import init_db, add_quip
from ships_ahoy.ticker_content import build_ship_chunks


@pytest.fixture
def conn():
    c = init_db(":memory:")
    c.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    c.execute("UPDATE settings SET value='0.1'  WHERE key='home_lon'")
    c.execute("UPDATE settings SET value='100'  WHERE key='distance_km'")
    c.commit()
    return c


def _make_ship(conn, mmsi=123456789, **kwargs):
    """Insert a ship row and return it as sqlite3.Row."""
    defaults = dict(
        name="MV Test", ship_type=70, flag="US",
        latitude=51.5, longitude=0.1, speed=8.5,
        heading=270.0, status=0, destination="Rotterdam",
        visit_count=3,
    )
    defaults.update(kwargs)
    now = "2025-01-01T00:00:00"
    conn.execute(
        """INSERT OR REPLACE INTO ships
           (mmsi, name, ship_type, flag, latitude, longitude,
            speed, heading, status, destination, visit_count,
            first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mmsi, defaults["name"], defaults["ship_type"], defaults["flag"],
         defaults["latitude"], defaults["longitude"], defaults["speed"],
         defaults["heading"], defaults["status"], defaults["destination"],
         defaults["visit_count"], now, now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM ships WHERE mmsi=?", (mmsi,)).fetchone()


def test_every_chunk_contains_ship_name(conn):
    ship = _make_ship(conn)
    chunks = build_ship_chunks(ship, None)
    assert all("MV Test" in c for c in chunks)


def test_identity_chunk_includes_type_and_flag(conn):
    ship = _make_ship(conn, flag="US", ship_type=70)
    chunks = build_ship_chunks(ship, None)
    assert any("cargo vessel" in c and "US" in c for c in chunks)


def test_identity_chunk_omits_flag_line_when_flag_none(conn):
    ship = _make_ship(conn, flag=None)
    chunks = build_ship_chunks(ship, None)
    assert not any("flag" in c for c in chunks)


def test_motion_chunk_present_when_speed_and_heading_set(conn):
    ship = _make_ship(conn, speed=8.5, heading=270.0)
    chunks = build_ship_chunks(ship, None)
    assert any("8.5 knots" in c for c in chunks)


def test_motion_chunk_absent_when_speed_none(conn):
    ship = _make_ship(conn, mmsi=100000001, speed=None)
    chunks = build_ship_chunks(ship, None)
    assert not any("knots" in c for c in chunks)


def test_position_chunk_present_when_distance_given(conn):
    ship = _make_ship(conn)
    chunks = build_ship_chunks(ship, None, distance_km=2.3, bearing_label="southwest")
    assert any("2.3 km" in c and "southwest" in c for c in chunks)


def test_position_chunk_absent_without_distance(conn):
    ship = _make_ship(conn)
    chunks = build_ship_chunks(ship, None)
    assert not any("km away" in c for c in chunks)


def test_status_chunk_absent_for_underway(conn):
    ship = _make_ship(conn, status=0)
    chunks = build_ship_chunks(ship, None)
    assert not any("currently" in c for c in chunks)


def test_status_chunk_present_for_anchored(conn):
    ship = _make_ship(conn, mmsi=100000002, status=1)
    chunks = build_ship_chunks(ship, None)
    assert any("at anchor" in c for c in chunks)


def test_destination_chunk_present_when_set(conn):
    ship = _make_ship(conn, destination="Rotterdam")
    chunks = build_ship_chunks(ship, None)
    assert any("Rotterdam" in c for c in chunks)


def test_destination_chunk_absent_when_none(conn):
    ship = _make_ship(conn, mmsi=100000003, destination=None)
    chunks = build_ship_chunks(ship, None)
    assert not any("bound for" in c for c in chunks)


def test_visit_count_plural(conn):
    ship = _make_ship(conn, visit_count=5)
    chunks = build_ship_chunks(ship, None)
    assert any("5 times" in c for c in chunks)


def test_visit_count_first_visit(conn):
    ship = _make_ship(conn, visit_count=1)
    chunks = build_ship_chunks(ship, None)
    assert any("first visit" in c for c in chunks)


def test_uses_enriched_name_over_ais_name(conn):
    ship = _make_ship(conn, name="AIS NAME")
    conn.execute(
        "INSERT INTO enrichment (mmsi, vessel_name) VALUES (?,?)",
        (ship["mmsi"], "ENRICHED NAME"),
    )
    conn.commit()
    enrich = conn.execute(
        "SELECT * FROM enrichment WHERE mmsi=?", (ship["mmsi"],)
    ).fetchone()
    chunks = build_ship_chunks(ship, enrich)
    assert all("ENRICHED NAME" in c for c in chunks)
    assert not any("AIS NAME" in c for c in chunks)


def test_size_chunk_when_enriched_with_length_and_year(conn):
    ship = _make_ship(conn)
    conn.execute(
        "INSERT INTO enrichment (mmsi, length_m, build_year) VALUES (?,?,?)",
        (ship["mmsi"], 185.0, 2003),
    )
    conn.commit()
    enrich = conn.execute(
        "SELECT * FROM enrichment WHERE mmsi=?", (ship["mmsi"],)
    ).fetchone()
    chunks = build_ship_chunks(ship, enrich)
    assert any("185" in c and "2003" in c for c in chunks)


def test_operator_chunk_when_enriched_with_owner(conn):
    ship = _make_ship(conn)
    conn.execute(
        "INSERT INTO enrichment (mmsi, owner) VALUES (?,?)",
        (ship["mmsi"], "Maersk Line"),
    )
    conn.commit()
    enrich = conn.execute(
        "SELECT * FROM enrichment WHERE mmsi=?", (ship["mmsi"],)
    ).fetchone()
    chunks = build_ship_chunks(ship, enrich)
    assert any("Maersk Line" in c for c in chunks)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_ticker_content.py -v
```
Expected: `ModuleNotFoundError: No module named 'ships_ahoy.ticker_content'`

- [ ] **Step 3: Create `ships_ahoy/ticker_content.py` with helpers and `build_ship_chunks`**

```python
"""Content generation for the ShipsAhoy LED ticker.

Builds prose-sentence chunks from ship and enrichment data, assembles
playlists for the continuous-cycle ticker service and web preview.

No I/O except DB reads — fully testable without hardware.

Usage::

    chunks = build_ship_chunks(ship_row, enrichment_row, distance_km=1.4, bearing_label="southwest")
    playlist = build_playlist(conn, cfg)
    for text in playlist:
        driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
"""

import random
import sqlite3
from typing import Optional

from ships_ahoy.config import Config
from ships_ahoy.db import get_active_quips, get_enrichment, get_ships_in_range
from ships_ahoy.distance import bearing_to_cardinal, distance_info

_STATUS_LABELS: dict[int, str] = {
    0: "underway",
    1: "at anchor",
    2: "not under command",
    3: "restricted manoeuvrability",
    4: "constrained by draught",
    5: "moored",
    6: "aground",
    7: "fishing",
    8: "underway sailing",
    15: "undefined",
}

# Status codes worth announcing (excludes 0=underway and 8=underway sailing)
_NOTEWORTHY_STATUSES: frozenset[int] = frozenset({1, 2, 3, 4, 5, 6, 7})

_CARDINAL_WORDS: dict[str, str] = {
    "N": "north", "NNE": "north-northeast", "NE": "northeast",
    "ENE": "east-northeast", "E": "east", "ESE": "east-southeast",
    "SE": "southeast", "SSE": "south-southeast", "S": "south",
    "SSW": "south-southwest", "SW": "southwest", "WSW": "west-southwest",
    "W": "west", "WNW": "west-northwest", "NW": "northwest",
    "NNW": "north-northwest",
}


def _type_label(ship_type: Optional[int]) -> str:
    if ship_type is None:
        return "vessel"
    if 70 <= ship_type <= 79:
        return "cargo vessel"
    if 80 <= ship_type <= 89:
        return "tanker"
    if 60 <= ship_type <= 69:
        return "passenger vessel"
    if 30 <= ship_type <= 39:
        return "fishing vessel"
    if 50 <= ship_type <= 59:
        return "service vessel"
    return "vessel"


def _cardinal_word(degrees: float) -> str:
    """Convert a bearing in degrees to a full compass-direction word."""
    abbr = bearing_to_cardinal(degrees)
    return _CARDINAL_WORDS.get(abbr, abbr)


def build_ship_chunks(
    ship_row: sqlite3.Row,
    enrichment_row: Optional[sqlite3.Row],
    distance_km: Optional[float] = None,
    bearing_label: Optional[str] = None,
) -> list[str]:
    """Return ordered prose chunks for one ship.

    Each chunk is a complete sentence containing the ship's name.
    Chunks for unavailable fields are omitted — no 'unknown' placeholders.
    """
    name: str = (
        enrichment_row["vessel_name"]
        if enrichment_row and enrichment_row["vessel_name"]
        else ship_row["name"]
    ) or "Unknown vessel"

    chunks: list[str] = []

    # 1. Identity
    flag = ship_row["flag"] or (enrichment_row["flag"] if enrichment_row else None)
    type_label = _type_label(ship_row["ship_type"])
    if flag:
        chunks.append(f"{name} is a {type_label} flying the {flag} flag")
    else:
        chunks.append(f"{name} is a {type_label}")

    # 2. Motion
    speed = ship_row["speed"]
    heading = ship_row["heading"]
    if speed is not None and heading is not None:
        direction = _cardinal_word(heading)
        chunks.append(f"{name} is traveling at {speed:.1f} knots heading {direction}")

    # 3. Position
    if distance_km is not None and bearing_label is not None:
        chunks.append(f"{name} is {distance_km:.1f} km away, to the {bearing_label}")

    # 4. Navigation status (only noteworthy ones)
    status = ship_row["status"]
    if status is not None and status in _NOTEWORTHY_STATUSES:
        chunks.append(f"{name} is currently {_STATUS_LABELS[status]}")

    # 5. Destination
    dest = ship_row["destination"]
    if dest and dest.strip() and dest.strip() != "0":
        chunks.append(f"{name} is bound for {dest.strip().title()}")

    # 6. Visit history
    visits = ship_row["visit_count"] or 1
    if visits == 1:
        chunks.append(f"This is {name}'s first visit to this area")
    else:
        chunks.append(f"{name} has visited this area {visits} times")

    # 7. Size and build year (requires enrichment)
    if enrichment_row:
        length = enrichment_row["length_m"]
        year = enrichment_row["build_year"]
        if length and year:
            chunks.append(f"{name} is {int(length)} meters long, built in {year}")
        elif length:
            chunks.append(f"{name} is {int(length)} meters long")

    # 8. Operator (requires enrichment)
    if enrichment_row and enrichment_row["owner"]:
        chunks.append(f"{name} is operated by {enrichment_row['owner']}")

    return chunks
```

- [ ] **Step 4: Run tests to confirm they pass**

```
uv run pytest tests/test_ticker_content.py -v
```
Expected: 16 PASSED

- [ ] **Step 5: Commit**

```
git add ships_ahoy/ticker_content.py tests/test_ticker_content.py
git commit -m "feat: add ticker_content module with build_ship_chunks"
```

---

## Task 3: `ticker_content.py` — playlist functions

**Files:**
- Modify: `ships_ahoy/ticker_content.py`
- Modify: `tests/test_ticker_content.py`

- [ ] **Step 1: Add failing tests for playlist functions**

Append to `tests/test_ticker_content.py`:
```python
from ships_ahoy.ticker_content import build_idle_chunks, build_playlist
from ships_ahoy.config import Config


def test_idle_chunks_starts_with_no_ships_message(conn):
    chunks = build_idle_chunks(conn)
    assert chunks[0] == "No ships in range"


def test_idle_chunks_includes_active_quips(conn):
    add_quip(conn, "A river runs through it", "location")
    add_quip(conn, "Why did the sailor fail math? Too many C's!", "quip")
    chunks = build_idle_chunks(conn)
    assert "A river runs through it" in chunks
    assert "Why did the sailor fail math? Too many C's!" in chunks


def test_idle_chunks_excludes_inactive_quips(conn):
    from ships_ahoy.db import toggle_quip
    qid = add_quip(conn, "Inactive quip", "quip")
    toggle_quip(conn, qid)
    chunks = build_idle_chunks(conn)
    assert "Inactive quip" not in chunks


def test_idle_chunks_shuffles_on_each_call(conn):
    for i in range(20):
        add_quip(conn, f"Quip {i}", "quip")
    first = build_idle_chunks(conn)
    second = build_idle_chunks(conn)
    # With 20 quips the probability of identical order is astronomically small
    assert first != second or len(first) <= 2


def test_build_playlist_returns_ship_chunks_when_ships_in_range(conn):
    _make_ship(conn, mmsi=200000001, latitude=51.5, longitude=0.1)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    assert len(playlist) > 0
    assert any("MV Test" in c for c in playlist)


def test_build_playlist_returns_idle_when_no_ships(conn):
    # conn has home configured but no ships
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    assert playlist[0] == "No ships in range"


def test_build_playlist_orders_closest_first(conn):
    _make_ship(conn, mmsi=200000002, name="MV Far",   latitude=51.9, longitude=0.1)
    _make_ship(conn, mmsi=200000003, name="MV Close", latitude=51.51, longitude=0.1)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    close_idx = next(i for i, c in enumerate(playlist) if "MV Close" in c)
    far_idx   = next(i for i, c in enumerate(playlist) if "MV Far" in c)
    assert close_idx < far_idx


def test_build_playlist_returns_idle_when_home_not_set(conn):
    conn.execute("UPDATE settings SET value=NULL WHERE key='home_lat'")
    conn.execute("UPDATE settings SET value=NULL WHERE key='home_lon'")
    conn.commit()
    _make_ship(conn, mmsi=200000004)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    assert playlist[0] == "No ships in range"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_ticker_content.py -v -k "idle or playlist"
```
Expected: `ImportError: cannot import name 'build_idle_chunks'`

- [ ] **Step 3: Append the three playlist functions to `ships_ahoy/ticker_content.py`**

```python
def get_in_range_ships_with_distance(
    conn: sqlite3.Connection,
    cfg: Config,
) -> list[tuple[sqlite3.Row, Optional[sqlite3.Row], float, str]]:
    """Return (ship_row, enrichment_row, distance_km, bearing_word) sorted closest-first.

    Returns an empty list if home location is not configured.
    """
    home = cfg.home_location
    if home is None:
        return []
    home_lat, home_lon = home
    ships = get_ships_in_range(conn, home_lat, home_lon, cfg.distance_km)
    result: list[tuple[sqlite3.Row, Optional[sqlite3.Row], float, str]] = []
    for ship in ships:
        km, cardinal = distance_info(home_lat, home_lon, ship["latitude"], ship["longitude"])
        bearing_word = _CARDINAL_WORDS.get(cardinal, cardinal)
        enrichment = get_enrichment(conn, ship["mmsi"])
        result.append((ship, enrichment, km, bearing_word))
    result.sort(key=lambda x: x[2])
    return result


def build_idle_chunks(conn: sqlite3.Connection) -> list[str]:
    """Return 'No ships in range' followed by shuffled active quips and location facts."""
    rows = get_active_quips(conn)
    texts = [r["text"] for r in rows]
    random.shuffle(texts)
    return ["No ships in range"] + texts


def build_playlist(conn: sqlite3.Connection, cfg: Config) -> list[str]:
    """Return the full scroll playlist for one cycle.

    If ships are in range: prose chunks for each ship, closest-first.
    If no ships (or home not configured): idle chunks.
    """
    ships_data = get_in_range_ships_with_distance(conn, cfg)
    if not ships_data:
        return build_idle_chunks(conn)
    playlist: list[str] = []
    for ship_row, enrichment_row, distance_km, bearing_label in ships_data:
        playlist.extend(build_ship_chunks(ship_row, enrichment_row, distance_km, bearing_label))
    return playlist
```

- [ ] **Step 4: Run the full ticker_content test suite**

```
uv run pytest tests/test_ticker_content.py -v
```
Expected: All tests PASSED.

- [ ] **Step 5: Run the full suite to check for regressions**

```
uv run pytest tests/ -v
```
Expected: All previously passing tests still pass.

- [ ] **Step 6: Commit**

```
git add ships_ahoy/ticker_content.py tests/test_ticker_content.py
git commit -m "feat: add playlist functions to ticker_content"
```

---

## Task 4: Rewrite `ticker_service.py`

**Files:**
- Rewrite: `services/ticker_service.py`
- Rewrite: `tests/test_ticker_service.py`

- [ ] **Step 1: Write the new test file**

Replace the entire contents of `tests/test_ticker_service.py` with:
```python
"""Tests for the ticker_service continuous cycle loop."""
import sys
import pytest
from unittest import mock
import importlib.util


def _load_ticker_service():
    """Load ticker_service with matrix_driver mocked to prevent hardware import errors."""
    spec = importlib.util.spec_from_file_location(
        "ticker_service", "services/ticker_service.py"
    )
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ships_ahoy.matrix_driver": mock.MagicMock()}):
        spec.loader.exec_module(mod)
    return mod


_ts_mod = _load_ticker_service()


def test_build_parser_esp32_port_arg():
    args = _ts_mod._build_parser().parse_args(["--esp32-port", "/dev/ttyAMA0"])
    assert args.esp32_port == "/dev/ttyAMA0"


def test_build_parser_esp32_port_defaults_to_none():
    args = _ts_mod._build_parser().parse_args([])
    assert args.esp32_port is None


def test_main_calls_scroll_text_for_each_chunk():
    """main() calls driver.scroll_text once per playlist chunk, then stops."""
    driver = mock.MagicMock()
    playlist = ["MV Test is a cargo vessel flying the US flag",
                "MV Test is traveling at 8.5 knots heading west"]
    scroll_calls = []

    def scroll_and_stop(text, speed_px_per_sec):
        scroll_calls.append(text)
        if len(scroll_calls) >= len(playlist):
            raise KeyboardInterrupt

    driver.scroll_text.side_effect = scroll_and_stop

    with mock.patch("sys.argv", ["ticker_service"]):
        with mock.patch.object(_ts_mod, "init_db", return_value=mock.MagicMock()):
            with mock.patch.object(_ts_mod, "Config", return_value=mock.MagicMock()):
                with mock.patch.object(_ts_mod, "build_playlist", return_value=playlist):
                    with mock.patch.object(_ts_mod, "_DriverClass", return_value=driver):
                        with pytest.raises(SystemExit) as exc:
                            _ts_mod.main()

    assert scroll_calls == playlist
    assert exc.value.code == 0


def test_main_clears_display_on_keyboard_interrupt():
    """KeyboardInterrupt triggers driver.clear() and sys.exit(0)."""
    driver = mock.MagicMock()
    driver.scroll_text.side_effect = KeyboardInterrupt

    with mock.patch("sys.argv", ["ticker_service"]):
        with mock.patch.object(_ts_mod, "init_db", return_value=mock.MagicMock()):
            with mock.patch.object(_ts_mod, "Config", return_value=mock.MagicMock()):
                with mock.patch.object(_ts_mod, "build_playlist", return_value=["chunk"]):
                    with mock.patch.object(_ts_mod, "_DriverClass", return_value=driver):
                        with pytest.raises(SystemExit) as exc:
                            _ts_mod.main()

    driver.clear.assert_called_once()
    assert exc.value.code == 0
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```
uv run pytest tests/test_ticker_service.py -v
```
Expected: failures because `_ts_mod` has no `build_playlist` attribute (old module doesn't import it).

- [ ] **Step 3: Rewrite `services/ticker_service.py`**

Replace the entire file with:
```python
"""LED Ticker Service for ShipsAhoy.

Drives the LED matrix display in a continuous cycle.
Runs as a persistent systemd service.

Responsibilities:
- Build a playlist of prose chunks from in-range ships (closest first)
- Scroll each chunk across the display
- Repeat, rebuilding the playlist on each cycle
- When no ships are in range, cycle through idle quips and location facts

MatrixDriver selection:
    Attempts to import RGBMatrixDriver (requires rpi-rgb-led-matrix on Pi).
    Falls back to StubMatrixDriver automatically on non-Pi platforms.

Usage::

    uv run python services/ticker_service.py [--db PATH] [--verbose] [--esp32-port PORT]
"""

import argparse
import sys
import time

from loguru import logger

from ships_ahoy.config import Config
from ships_ahoy.db import init_db
from ships_ahoy.ticker_content import build_playlist
from ships_ahoy.service_utils import DEFAULT_DB_PATH, configure_logging

try:
    from ships_ahoy.matrix_driver import RGBMatrixDriver as _DriverClass
except (ImportError, NotImplementedError):
    from ships_ahoy.matrix_driver import StubMatrixDriver as _DriverClass  # type: ignore[assignment]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticker_service",
        description="ShipsAhoy LED Ticker Service",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--esp32-port", default=None, metavar="PORT",
        help="UART device for ESP32, e.g. /dev/ttyAMA0",
    )
    return parser


def main() -> None:
    """Service entry point. Continuously cycles through ship info and idle content."""
    args = _build_parser().parse_args()
    configure_logging(args.verbose)

    conn = init_db(args.db)
    cfg = Config(conn)

    if args.esp32_port:
        from ships_ahoy.matrix_driver import ESP32Driver
        driver = ESP32Driver(port=args.esp32_port)
        logger.info("Using ESP32Driver on {}", args.esp32_port)
    else:
        driver = _DriverClass()

    logger.info("Ticker service starting.")

    while True:
        try:
            playlist = build_playlist(conn, cfg)
            for text in playlist:
                logger.info("Ticker: {}", text)
                driver.scroll_text(text, speed_px_per_sec=cfg.scroll_speed)
        except KeyboardInterrupt:
            logger.info("Ticker service stopped by user.")
            driver.clear()
            sys.exit(0)
        except Exception:
            logger.exception("Ticker service loop error")
            time.sleep(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the new tests to confirm they pass**

```
uv run pytest tests/test_ticker_service.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Run the full suite**

```
uv run pytest tests/ -v
```
Expected: All tests pass.

- [ ] **Step 6: Commit**

```
git add services/ticker_service.py tests/test_ticker_service.py
git commit -m "refactor: replace event-driven ticker loop with continuous cycle"
```

---

## Task 5: `/quips` web routes and template

**Files:**
- Modify: `services/web_service.py`
- Create: `templates/quips.html`
- Modify: `tests/test_web_service.py`

- [ ] **Step 1: Add failing tests for quips routes**

Append to `tests/test_web_service.py`:
```python
from ships_ahoy.db import add_quip, get_all_quips, toggle_quip


def test_quips_page_returns_200(client):
    c, conn = client
    resp = c.get("/quips")
    assert resp.status_code == 200


def test_quips_page_shows_table(client):
    c, conn = client
    add_quip(conn, "A funny joke", "quip")
    resp = c.get("/quips")
    assert b"A funny joke" in resp.data


def test_add_quip_via_post_redirects(client):
    c, conn = client
    resp = c.post("/quips/add", data={"text": "Hello river!", "category": "location"})
    assert resp.status_code == 302


def test_add_quip_via_post_persists_to_db(client):
    c, conn = client
    c.post("/quips/add", data={"text": "Hello river!", "category": "location"})
    rows = get_all_quips(conn)
    assert any(r["text"] == "Hello river!" for r in rows)


def test_toggle_quip_via_post_deactivates(client):
    c, conn = client
    qid = add_quip(conn, "Toggle me", "quip")
    c.post(f"/quips/{qid}/toggle")
    row = conn.execute("SELECT active FROM quips WHERE id=?", (qid,)).fetchone()
    assert row["active"] == 0


def test_delete_quip_via_post_removes_row(client):
    c, conn = client
    qid = add_quip(conn, "Delete me", "quip")
    c.post(f"/quips/{qid}/delete")
    rows = get_all_quips(conn)
    assert not any(r["id"] == qid for r in rows)


def test_add_quip_ignores_empty_text(client):
    c, conn = client
    c.post("/quips/add", data={"text": "   ", "category": "quip"})
    assert get_all_quips(conn) == []
```

- [ ] **Step 2: Run failing tests to confirm 404s**

```
uv run pytest tests/test_web_service.py -v -k "quip"
```
Expected: FAILED — 404 responses.

- [ ] **Step 3: Add quips imports to `services/web_service.py`**

In the `from ships_ahoy.db import (...)` block, add these four names:
```python
    get_all_quips,
    add_quip,
    toggle_quip,
    delete_quip,
```

- [ ] **Step 4: Add the four quips routes to `services/web_service.py`**

Add before the `if __name__ == "__main__":` block (or with the other routes):
```python
@app.route("/quips")
def quips_page():
    quips = get_all_quips(_conn)
    return render_template("quips.html", quips=quips)


@app.route("/quips/add", methods=["POST"])
def add_quip_route():
    text = request.form.get("text", "").strip()
    category = request.form.get("category", "quip")
    if text and category in ("quip", "location"):
        add_quip(_conn, text, category)
    return redirect(url_for("quips_page"))


@app.route("/quips/<int:quip_id>/toggle", methods=["POST"])
def toggle_quip_route(quip_id: int):
    toggle_quip(_conn, quip_id)
    return redirect(url_for("quips_page"))


@app.route("/quips/<int:quip_id>/delete", methods=["POST"])
def delete_quip_route(quip_id: int):
    delete_quip(_conn, quip_id)
    return redirect(url_for("quips_page"))
```

Make sure `redirect` and `url_for` are in the Flask import at the top of `web_service.py`. If not already there, add them:
```python
from flask import Flask, render_template, request, redirect, url_for, Response, stream_with_context
```

- [ ] **Step 5: Create `templates/quips.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ShipsAhoy — Ticker Quips</title>
  <style>
    body { font-family: monospace; max-width: 700px; margin: 2em auto; }
    h1 { margin-bottom: 0.5em; }
    .add-form { display: flex; gap: 0.5em; margin-bottom: 1.5em; flex-wrap: wrap; }
    .add-form input[type=text] { flex: 1; padding: 0.4em; font-family: monospace; min-width: 200px; }
    .add-form select, .add-form button { padding: 0.4em 0.8em; font-family: monospace; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 0.4em 0.6em; border-bottom: 1px solid #ccc; }
    th { background: #f0f0f0; }
    .inactive { color: #999; }
    .actions form { display: inline; }
    .actions button { padding: 0.2em 0.6em; font-family: monospace; cursor: pointer; }
    a { color: inherit; }
  </style>
</head>
<body>
  <a href="/">← Back</a>
  <h1>Ticker Quips</h1>

  <form class="add-form" method="POST" action="/quips/add">
    <input type="text" name="text" placeholder="Enter quip or location fact" required>
    <select name="category">
      <option value="quip">Quip / Joke</option>
      <option value="location">Location Fact</option>
    </select>
    <button type="submit">Add</button>
  </form>

  <table>
    <thead>
      <tr>
        <th>Text</th>
        <th>Category</th>
        <th>Active</th>
        <th class="actions">Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for q in quips %}
      <tr class="{{ '' if q['active'] else 'inactive' }}">
        <td>{{ q['text'] }}</td>
        <td>{{ q['category'] }}</td>
        <td>{{ 'Yes' if q['active'] else 'No' }}</td>
        <td class="actions">
          <form method="POST" action="/quips/{{ q['id'] }}/toggle">
            <button type="submit">{{ 'Deactivate' if q['active'] else 'Activate' }}</button>
          </form>
          <form method="POST" action="/quips/{{ q['id'] }}/delete"
                onsubmit="return confirm('Delete this quip?')">
            <button type="submit">Delete</button>
          </form>
        </td>
      </tr>
    {% else %}
      <tr><td colspan="4">No quips yet. Add one above.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</body>
</html>
```

- [ ] **Step 6: Run the quips tests**

```
uv run pytest tests/test_web_service.py -v -k "quip"
```
Expected: 7 PASSED

- [ ] **Step 7: Run the full suite**

```
uv run pytest tests/ -v
```
Expected: All tests pass.

- [ ] **Step 8: Commit**

```
git add services/web_service.py templates/quips.html tests/test_web_service.py
git commit -m "feat: add /quips CRUD routes and template"
```

---

## Task 6: Rewrite the preview SSE endpoint

**Files:**
- Modify: `services/web_service.py`
- Modify: `tests/test_web_service.py`

- [ ] **Step 1: Add a failing test that verifies scrolling content appears**

Append to `tests/test_web_service.py`:
```python
def test_ticker_preview_uses_build_playlist(client):
    """SSE preview calls build_playlist; frames are emitted for each chunk."""
    import json as _json
    c, conn = client
    # Insert a ship so build_playlist returns ship chunks
    from ships_ahoy.db import init_db as _init_db
    from ships_ahoy.ship_tracker import ShipInfo
    from datetime import datetime
    upsert_ship(conn, ShipInfo(
        mmsi=987654321, name="MV Preview",
        latitude=51.5, longitude=0.1,
        last_seen=datetime.now(),
    ))
    conn.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    conn.execute("UPDATE settings SET value='0.1' WHERE key='home_lon'")
    conn.execute("UPDATE settings SET value='100' WHERE key='distance_km'")
    conn.commit()

    resp = c.get("/ticker/preview", query_string={"_max_frames": "2"})
    body = resp.data.decode()
    data_lines = [l for l in body.splitlines() if l.startswith("data:")]
    assert len(data_lines) == 2
    payload = _json.loads(data_lines[0][5:].strip())
    assert "pixels" in payload
```

- [ ] **Step 2: Run the test to confirm current behaviour**

```
uv run pytest tests/test_web_service.py::test_ticker_preview_uses_build_playlist -v
```
This may pass or fail depending on the existing implementation — note the result either way before proceeding.

- [ ] **Step 3: Add `build_playlist` import and remove `get_display_state` from `web_service.py`**

In the `from ships_ahoy.db import (...)` block in `services/web_service.py`, remove:
```python
    get_display_state,
```

Add a new import line after the db imports:
```python
from ships_ahoy.ticker_content import build_playlist
```

- [ ] **Step 4: Rewrite the `ticker_preview` SSE generator in `services/web_service.py`**

Replace the entire `ticker_preview` function (the `@app.route("/ticker/preview")` function and its nested `generate()`) with:

```python
@app.route("/ticker/preview")
def ticker_preview():
    """Server-Sent Events stream of rendered ticker frames at ~30 FPS.

    Each SSE client opens its own SQLite connection and Config instance.
    Uses build_playlist() directly — the same content the ticker service displays —
    so the preview is always accurate regardless of display_state timing.
    """
    max_frames = request.args.get("_max_frames", type=int)

    def generate():
        import sqlite3 as _sqlite3
        import json as _json

        conn = _sqlite3.connect(_db_path)
        conn.row_factory = _sqlite3.Row
        cfg = Config(conn)
        preview = PreviewDriver(
            display_width=ESP32_DISPLAY_WIDTH,
            display_height=ESP32_DISPLAY_HEIGHT,
        )

        FRAME_INTERVAL = 1.0 / 30.0
        GLYPH_WIDTH_PX = 6
        frame_count = 0

        try:
            while True:
                playlist = build_playlist(conn, cfg)
                for text in playlist:
                    speed = cfg.scroll_speed
                    preview.scroll_text(text, speed_px_per_sec=speed)
                    text_px = max(ESP32_DISPLAY_WIDTH, len(text) * GLYPH_WIDTH_PX)
                    duration_sec = text_px / max(speed, 1.0)
                    elapsed = 0.0
                    while elapsed < duration_sec:
                        frame = preview.get_current_frame(elapsed_sec=FRAME_INTERVAL)
                        flat = [list(px) for row in frame for px in row]
                        yield (
                            f"data: {_json.dumps({'pixels': flat, 'width': ESP32_DISPLAY_WIDTH, 'height': ESP32_DISPLAY_HEIGHT})}\n\n"
                        )
                        frame_count += 1
                        if max_frames and frame_count >= max_frames:
                            return
                        time.sleep(FRAME_INTERVAL)
                        elapsed += FRAME_INTERVAL
        finally:
            conn.close()

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
    )
```

- [ ] **Step 5: Run all web service tests**

```
uv run pytest tests/test_web_service.py -v
```
Expected: All PASSED.

- [ ] **Step 6: Run the full suite**

```
uv run pytest tests/ -v
```
Expected: All tests pass.

- [ ] **Step 7: Commit**

```
git add services/web_service.py tests/test_web_service.py
git commit -m "fix: rewrite ticker preview SSE to use build_playlist directly"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Continuous cycle replacing event-driven — Task 4
- [x] Prose chunks per ship, name in every sentence — Task 2
- [x] Closest-first ordering — Task 3
- [x] Idle pool: "No ships in range" lead-in + shuffled quips — Task 3
- [x] Quips table with category, active flag — Task 1
- [x] Web portal CRUD for quips — Task 5
- [x] Preview fix: build_playlist directly in SSE — Task 6
- [x] Events table untouched (ais_service unchanged) — no task needed
- [x] All existing settings still respected (scroll_speed, distance_km, home_lat/lon) — no task needed

**Type consistency:** `build_playlist(conn, cfg)` signature consistent across Task 3 definition, Task 4 ticker_service usage, and Task 6 web_service usage. `build_ship_chunks(ship_row, enrichment_row, distance_km, bearing_label)` signature consistent across Task 2 definition and Task 3 caller.

**No placeholders:** All steps contain complete code.
