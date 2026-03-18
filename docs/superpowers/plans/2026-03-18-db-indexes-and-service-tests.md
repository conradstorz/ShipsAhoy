# DB Indexes & Service Integration Tests Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six SQLite indexes to eliminate full-table scans, then write integration tests for all four services against a real `:memory:` database.

**Architecture:** Indexes are added directly to `init_db()` so they apply on every DB open. Service tests import each service module, call its internal functions with a seeded `:memory:` DB, and mock only external I/O (HTTP, serial, AIS socket).

**Tech Stack:** Python, pytest, sqlite3, unittest.mock, Flask test client

---

## Chunk 1: DB Indexes

### Task 1: Add indexes to `init_db()` and verify

**Files:**
- Modify: `ships_ahoy/db.py` — add 6 `CREATE INDEX IF NOT EXISTS` statements in `init_db()`
- Modify: `tests/test_db.py` — add index existence test

---

- [ ] **Step 1.1: Write the failing index test**

Add this test at the end of `tests/test_db.py`:

```python
def test_indexes_exist(conn):
    """All expected indexes must be created by init_db()."""
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()}
    expected = [
        "idx_ships_last_seen",
        "idx_ships_enriched",
        "idx_ships_position",
        "idx_events_pending",
        "idx_events_recent",
        "idx_visits_mmsi",
    ]
    for idx in expected:
        assert idx in names, f"Missing index: {idx}"
```

- [ ] **Step 1.2: Run test to confirm it fails**

```bash
uv run pytest tests/test_db.py::test_indexes_exist -v
```

Expected: `FAILED — AssertionError: Missing index: idx_ships_last_seen`

- [ ] **Step 1.3: Add index DDL to `init_db()` in `ships_ahoy/db.py`**

After the six `conn.execute(_CREATE_*)` calls and before `conn.executemany(...)`, add:

```python
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_ships_last_seen ON ships (last_seen)"
)
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_ships_enriched ON ships (enriched)"
)
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_ships_position ON ships (latitude, longitude)"
    " WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
)
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_events_pending ON events (displayed_at, created_at)"
    " WHERE displayed_at IS NULL"
)
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_events_recent ON events (created_at)"
)
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_visits_mmsi ON ship_visits (mmsi)"
)
```

- [ ] **Step 1.4: Run test to confirm it passes**

```bash
uv run pytest tests/test_db.py::test_indexes_exist -v
```

Expected: `PASSED`

- [ ] **Step 1.5: Run full test suite to check nothing broke**

```bash
uv run pytest tests/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 1.6: Commit**

```bash
git add ships_ahoy/db.py tests/test_db.py
git commit -m "feat: add six SQLite indexes to init_db() for query performance"
```

---

## Chunk 2: AIS Service Tests

### Task 2: Create `tests/test_ais_service.py`

**Files:**
- Create: `tests/test_ais_service.py`

**Key design notes:**
- `services/ais_service.py` has a module-level `_tracker = ShipTracker()`. Reset it before each test with an `autouse` fixture.
- Mock `svc._tracker.update` to return a `ShipInfo` directly — avoids needing valid NMEA sentences.
- Patch `services.ais_service.time.sleep` (not `time.sleep` globally).
- Patch `services.ais_service.AISReceiver` (not `ships_ahoy.ais_receiver.AISReceiver`).

---

- [ ] **Step 2.1: Create the test file with fixtures**

Create `tests/test_ais_service.py`:

```python
"""Integration tests for services/ais_service.py.

Tests call internal functions directly against a real :memory: SQLite database.
External I/O (sockets, time.sleep) is mocked.
"""
import socket
from datetime import datetime, timedelta
from unittest import mock

import pytest

import services.ais_service as svc
from ships_ahoy.config import Config
from ships_ahoy.db import init_db, get_ship, record_visit
from ships_ahoy.events import EventType
from ships_ahoy.ship_tracker import ShipInfo, ShipTracker


@pytest.fixture
def conn():
    """In-memory DB with home location set to London (51.5, 0.0)."""
    c = init_db(":memory:")
    c.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    c.execute("UPDATE settings SET value='0.0' WHERE key='home_lon'")
    c.commit()
    return c


@pytest.fixture
def cfg(conn):
    return Config(conn)


@pytest.fixture(autouse=True)
def reset_tracker():
    """Replace the module-level tracker with a fresh one before each test."""
    svc._tracker = ShipTracker()


def _make_ship(mmsi=123456789, lat=51.5, lon=0.0, status=0, name="MV Test"):
    """Helper: return a ShipInfo near London."""
    return ShipInfo(
        mmsi=mmsi,
        name=name,
        latitude=lat,
        longitude=lon,
        status=status,
        last_seen=datetime.now(),
    )
```

- [ ] **Step 2.2: Add `test_new_ship_writes_arrived_event`**

```python
def test_new_ship_writes_arrived_event(conn, cfg):
    """New ship within home range → ARRIVED event + open visit recorded."""
    ship = _make_ship()
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=ship):
        svc._process_message(conn, msg, cfg)

    events = conn.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.ARRIVED

    visits = conn.execute("SELECT * FROM ship_visits").fetchall()
    assert len(visits) == 1
    assert visits[0]["departed_at"] is None
```

- [ ] **Step 2.3: Add `test_new_ship_outside_range_no_event`**

```python
def test_new_ship_outside_range_no_event(conn, cfg):
    """Ship far from home (equator) → no event, no visit."""
    ship = _make_ship(lat=0.0, lon=0.0)
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=ship):
        svc._process_message(conn, msg, cfg)

    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ship_visits").fetchone()[0] == 0
```

- [ ] **Step 2.4: Add `test_status_change_writes_event`**

```python
def test_status_change_writes_event(conn, cfg):
    """Existing ship changes nav status → STATUS_CHANGE event written."""
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, status, last_seen, first_seen)"
        " VALUES (?, ?, ?, ?, ?)",
        (123456789, "MV Test", 0, now, now),
    )
    conn.commit()

    new_ship = _make_ship(status=5)  # 5 = moored
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=new_ship):
        svc._process_message(conn, msg, cfg)

    events = conn.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.STATUS_CHANGE
```

- [ ] **Step 2.5: Add `test_no_home_location_treats_all_noteworthy`**

```python
def test_no_home_location_treats_all_noteworthy():
    """When home_lat/lon are NULL, every ship gets events regardless of position."""
    # Use a fresh connection — do NOT set home_lat/lon so they stay NULL
    conn = init_db(":memory:")
    cfg = Config(conn)
    ship = _make_ship(lat=0.0, lon=0.0)  # far from London, but home is unset
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=ship):
        svc._process_message(conn, msg, cfg)

    events = conn.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.ARRIVED
```

- [ ] **Step 2.6: Add `test_message_returns_none_is_noop`**

```python
def test_message_returns_none_is_noop(conn, cfg):
    """Tracker returning None (unrecognised message type) → no DB writes."""
    msg = mock.MagicMock()
    with mock.patch.object(svc._tracker, "update", return_value=None):
        svc._process_message(conn, msg, cfg)

    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ships").fetchone()[0] == 0
```

- [ ] **Step 2.7: Add stale sweep tests**

```python
def test_run_stale_sweep_marks_departed(conn, cfg):
    """Ship with open visit last seen 2 hours ago → DEPARTED event written."""
    old_time = (datetime.now() - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?, ?, ?, ?)",
        (111222333, "Stale Ship", old_time, old_time),
    )
    conn.execute(
        "INSERT INTO ship_visits (mmsi, arrived_at) VALUES (?, ?)",
        (111222333, old_time),
    )
    conn.commit()

    svc._run_stale_sweep(conn, cfg)

    events = conn.execute(
        "SELECT * FROM events WHERE mmsi=111222333"
    ).fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.DEPARTED

    visit = conn.execute(
        "SELECT * FROM ship_visits WHERE mmsi=111222333"
    ).fetchone()
    assert visit["departed_at"] is not None


def test_run_stale_sweep_skips_fresh_ships(conn, cfg):
    """Ship last seen moments ago → no DEPARTED event."""
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?, ?, ?, ?)",
        (999888777, "Fresh Ship", now, now),
    )
    conn.execute(
        "INSERT INTO ship_visits (mmsi, arrived_at) VALUES (?, ?)",
        (999888777, now),
    )
    conn.commit()

    svc._run_stale_sweep(conn, cfg)

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE mmsi=999888777"
    ).fetchone()[0] == 0
```

- [ ] **Step 2.8: Add backoff tests**

```python
def test_connect_with_backoff_succeeds(monkeypatch):
    """Successful TCP check → returns an AISReceiver instance."""
    mock_receiver = mock.MagicMock()
    monkeypatch.setattr("socket.create_connection", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr("services.ais_service.AISReceiver", lambda **kw: mock_receiver)

    result = svc._connect_with_backoff("localhost", 10110, use_udp=False)
    assert result is mock_receiver


def test_connect_with_backoff_retries(monkeypatch):
    """First connection attempt fails, second succeeds → time.sleep called once."""
    call_count = {"n": 0}

    def flaky_connect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionRefusedError("refused")
        return mock.MagicMock()

    sleep_calls = []
    monkeypatch.setattr("socket.create_connection", flaky_connect)
    monkeypatch.setattr("services.ais_service.AISReceiver", lambda **kw: mock.MagicMock())
    monkeypatch.setattr("services.ais_service.time.sleep", lambda s: sleep_calls.append(s))

    svc._connect_with_backoff("localhost", 10110, use_udp=False)

    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 1  # first backoff delay is 1 second
```

- [ ] **Step 2.9: Run all ais_service tests**

```bash
uv run pytest tests/test_ais_service.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 2.10: Commit**

```bash
git add tests/test_ais_service.py
git commit -m "test: add integration tests for ais_service"
```

---

## Chunk 3: Enrichment Service Refactor + Tests

### Task 3: Extract `_process_one_ship` helper

**Files:**
- Modify: `services/enrichment_service.py` — extract inner loop body to `_process_one_ship(conn, mmsi, photos_dir)`

---

- [ ] **Step 3.1: Write the failing test first**

Create `tests/test_enrichment_service.py` with just the two main-loop tests that require `_process_one_ship`:

```python
"""Integration tests for services/enrichment_service.py."""
import pytest
from pathlib import Path
from unittest import mock

import services.enrichment_service as svc
from ships_ahoy.db import init_db
from ships_ahoy.events import EventType


@pytest.fixture
def conn():
    return init_db(":memory:")


@pytest.fixture
def photos_dir(tmp_path):
    d = tmp_path / "photos"
    d.mkdir()
    return d


def test_process_one_ship_enriches_ship(conn, photos_dir):
    """Successful scrape → enrichment row saved, ENRICHED event written."""
    now = __import__("datetime").datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?, ?, ?, ?)",
        (123456789, "MV Test", now, now),
    )
    conn.commit()

    fake_data = {"vessel_name": "MV Test", "source": "shipxplorer", "flag": "NO"}
    with mock.patch.object(svc, "_enrich_ship", return_value=fake_data):
        svc._process_one_ship(conn, 123456789, photos_dir)

    enrichment = conn.execute(
        "SELECT * FROM enrichment WHERE mmsi=123456789"
    ).fetchone()
    assert enrichment is not None
    assert enrichment["vessel_name"] == "MV Test"

    events = conn.execute(
        "SELECT * FROM events WHERE mmsi=123456789"
    ).fetchall()
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.ENRICHED

    ship = conn.execute("SELECT enriched FROM ships WHERE mmsi=123456789").fetchone()
    assert ship["enriched"] == 1


def test_process_one_ship_increments_attempts_on_failure(conn, photos_dir):
    """All scrapers fail → fetch_attempts incremented, no ENRICHED event."""
    now = __import__("datetime").datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?, ?, ?, ?)",
        (987654321, "MV Unknown", now, now),
    )
    conn.commit()

    with mock.patch.object(svc, "_enrich_ship", return_value=None):
        svc._process_one_ship(conn, 987654321, photos_dir)

    row = conn.execute(
        "SELECT fetch_attempts FROM enrichment WHERE mmsi=987654321"
    ).fetchone()
    assert row is not None
    assert row["fetch_attempts"] == 1

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE mmsi=987654321"
    ).fetchone()[0] == 0
```

- [ ] **Step 3.2: Run to confirm it fails (function doesn't exist yet)**

```bash
uv run pytest tests/test_enrichment_service.py::test_process_one_ship_enriches_ship -v
```

Expected: `AttributeError: module 'services.enrichment_service' has no attribute '_process_one_ship'`

- [ ] **Step 3.3: Extract `_process_one_ship` in `services/enrichment_service.py`**

Add this function after `_enrich_ship`:

```python
def _process_one_ship(conn, mmsi: int, photos_dir: Path) -> None:
    """Enrich one ship: try scrapers, save result or increment fetch attempts."""
    data = _enrich_ship(mmsi, photos_dir)
    if data:
        if data.get("photo_url"):
            local_path = _download_photo(data["photo_url"], mmsi, photos_dir)
            if local_path:
                data["photo_path"] = local_path
        save_enrichment(conn, mmsi, data)
        write_event(conn, mmsi, EventType.ENRICHED,
                    f"New enrichment data for MMSI {mmsi}")
        logger.info("Enriched MMSI %d from %s", mmsi, data.get("source"))
    else:
        increment_fetch_attempts(conn, mmsi)
        logger.debug("No data found for MMSI %d", mmsi)
```

Replace the inner loop body in `main()`:

```python
# Before (inside for mmsi in mmsi_list:):
            for mmsi in mmsi_list:
                try:
                    data = _enrich_ship(mmsi, photos_dir)
                    if data:
                        if data.get("photo_url"):
                            local_path = _download_photo(data["photo_url"], mmsi, photos_dir)
                            if local_path:
                                data["photo_path"] = local_path
                        save_enrichment(conn, mmsi, data)
                        write_event(conn, mmsi, EventType.ENRICHED,
                                    f"New enrichment data for MMSI {mmsi}")
                        logger.info("Enriched MMSI %d from %s", mmsi, data.get("source"))
                    else:
                        increment_fetch_attempts(conn, mmsi)
                        logger.debug("No data found for MMSI %d", mmsi)
                except Exception:
                    logger.exception("Error enriching MMSI %d", mmsi)

                time.sleep(delay)

# After:
            for mmsi in mmsi_list:
                try:
                    _process_one_ship(conn, mmsi, photos_dir)
                except Exception:
                    logger.exception("Error enriching MMSI %d", mmsi)

                time.sleep(delay)
```

- [ ] **Step 3.4: Run the two new tests**

```bash
uv run pytest tests/test_enrichment_service.py::test_process_one_ship_enriches_ship tests/test_enrichment_service.py::test_process_one_ship_increments_attempts_on_failure -v
```

Expected: both pass.

- [ ] **Step 3.5: Commit the refactor**

```bash
git add services/enrichment_service.py tests/test_enrichment_service.py
git commit -m "refactor: extract _process_one_ship from enrichment_service.main()"
```

---

### Task 4: Complete `tests/test_enrichment_service.py`

---

- [ ] **Step 4.1: Add HTML fixtures and scraper tests**

Append to `tests/test_enrichment_service.py`:

```python
# ── HTML Fixtures ──────────────────────────────────────────────────────────────

_SHIPXPLORER_HTML = """
<html><body>
<h1>MV Example</h1>
<table>
  <tr><td>Flag</td><td>Norway</td></tr>
  <tr><td>IMO</td><td>9876543</td></tr>
  <tr><td>Call Sign</td><td>LABC1</td></tr>
  <tr><td>Type</td><td>Cargo</td></tr>
  <tr><td>Length</td><td>150.5 m</td></tr>
  <tr><td>Built</td><td>2005</td></tr>
</table>
</body></html>
"""

_ITU_HTML = """
<html><body>
<table>
  <tr><th>Name</th><th>Call Sign</th><th>Flag</th></tr>
  <tr><td>MV Example</td><td>LABC1</td><td>Norway</td></tr>
</table>
</body></html>
"""

_CLOUDFLARE_HTML = """
<html><body>Checking your browser... cloudflare protection active</body></html>
"""


def _mock_get(html: str, status_code: int = 200):
    """Return a mock requests.Response with given HTML body."""
    resp = mock.MagicMock()
    resp.text = html
    resp.status_code = status_code
    resp.raise_for_status = mock.MagicMock()
    return resp


# ── ShipXplorer scraper ────────────────────────────────────────────────────────

def test_scrape_shipxplorer_parses_vessel_name():
    with mock.patch("services.enrichment_service.requests.get",
                    return_value=_mock_get(_SHIPXPLORER_HTML)):
        result = svc._scrape_shipxplorer(123456789)
    assert result is not None
    assert result["vessel_name"] == "MV Example"


def test_scrape_shipxplorer_parses_table_fields():
    with mock.patch("services.enrichment_service.requests.get",
                    return_value=_mock_get(_SHIPXPLORER_HTML)):
        result = svc._scrape_shipxplorer(123456789)
    assert result["flag"] == "Norway"
    assert result["imo"] == "9876543"
    assert result["call_sign"] == "LABC1"
    assert result["ship_type_label"] == "Cargo"
    assert result["length_m"] == 150.5
    assert result["build_year"] == 2005


def test_scrape_shipxplorer_raises_on_http_error():
    """_scrape_shipxplorer propagates HTTP errors (caught by _enrich_ship's try/except)."""
    from requests.exceptions import HTTPError
    resp = mock.MagicMock()
    resp.raise_for_status.side_effect = HTTPError("404")
    with mock.patch("services.enrichment_service.requests.get", return_value=resp):
        with pytest.raises(HTTPError):
            svc._scrape_shipxplorer(123456789)


# ── MarineTraffic scraper ──────────────────────────────────────────────────────

def test_scrape_marinetraffic_cloudflare_returns_none():
    with mock.patch("services.enrichment_service.requests.get",
                    return_value=_mock_get(_CLOUDFLARE_HTML)):
        result = svc._scrape_marinetraffic(123456789)
    assert result is None


# ── ITU scraper ────────────────────────────────────────────────────────────────

def test_scrape_itu_parses_table_row():
    with mock.patch("services.enrichment_service.requests.post",
                    return_value=_mock_get(_ITU_HTML)):
        result = svc._scrape_itu(123456789)
    assert result is not None
    assert result["vessel_name"] == "MV Example"
    assert result["call_sign"] == "LABC1"
    assert result["flag"] == "Norway"


# ── _enrich_ship priority chain ────────────────────────────────────────────────

def test_enrich_ship_returns_first_success(photos_dir):
    fake = {"vessel_name": "MV First", "source": "shipxplorer"}
    with mock.patch.object(svc, "_scrape_shipxplorer", return_value=fake) as m1, \
         mock.patch.object(svc, "_scrape_marinetraffic") as m2:
        result = svc._enrich_ship(123456789, photos_dir)
    assert result == fake
    m2.assert_not_called()


def test_enrich_ship_falls_through_on_failure(photos_dir):
    itu_data = {"vessel_name": "MV Third", "source": "itu"}
    with mock.patch.object(svc, "_scrape_shipxplorer", side_effect=Exception("fail")), \
         mock.patch.object(svc, "_scrape_marinetraffic", return_value=None), \
         mock.patch.object(svc, "_scrape_itu", return_value=itu_data):
        result = svc._enrich_ship(123456789, photos_dir)
    assert result == itu_data


def test_enrich_ship_all_fail_returns_none(photos_dir):
    with mock.patch.object(svc, "_scrape_shipxplorer", side_effect=Exception), \
         mock.patch.object(svc, "_scrape_marinetraffic", side_effect=Exception), \
         mock.patch.object(svc, "_scrape_itu", side_effect=Exception):
        result = svc._enrich_ship(123456789, photos_dir)
    assert result is None


# ── _download_photo ────────────────────────────────────────────────────────────

def test_download_photo_saves_file(tmp_path):
    resp = mock.MagicMock()
    resp.headers = {"content-type": "image/jpeg"}
    resp.raise_for_status = mock.MagicMock()
    resp.iter_content.return_value = [b"fake image bytes"]
    with mock.patch("services.enrichment_service.requests.get", return_value=resp):
        path = svc._download_photo("http://example.com/ship.jpg", 111222333, tmp_path)
    assert path is not None
    assert (tmp_path / "111222333.jpg").exists()


def test_download_photo_wrong_content_type_returns_none(tmp_path):
    resp = mock.MagicMock()
    resp.headers = {"content-type": "text/html"}
    resp.raise_for_status = mock.MagicMock()
    with mock.patch("services.enrichment_service.requests.get", return_value=resp):
        path = svc._download_photo("http://example.com/ship.jpg", 111222333, tmp_path)
    assert path is None
    assert not (tmp_path / "111222333.jpg").exists()
```

- [ ] **Step 4.2: Run all enrichment tests**

```bash
uv run pytest tests/test_enrichment_service.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 4.3: Commit**

```bash
git add tests/test_enrichment_service.py
git commit -m "test: add integration tests for enrichment_service"
```

---

## Chunk 4: Ticker & Web Service Tests

### Task 5: Expand `tests/test_ticker_service.py`

**Files:**
- Modify: `tests/test_ticker_service.py`

**Key design notes:**
- Import service functions lazily with `matrix_driver` mocked (same pattern as existing tests).
- Pass a `MagicMock()` driver directly to `_display_event`, `_show_idle`, `_handle_overflow` — they all accept `driver` as a parameter.
- Backdated events must be inserted with direct SQL since `write_event` always uses `_now_iso()`.

---

- [ ] **Step 5.1: Add module-level import of ticker service functions**

Add this block at the top of `tests/test_ticker_service.py`, after the existing imports:

```python
import importlib.util
from pathlib import Path

# Load ticker_service with matrix_driver mocked to prevent hardware import errors
_ts_spec = importlib.util.spec_from_file_location(
    "ticker_service_full", "services/ticker_service.py"
)
_ts_mod = importlib.util.module_from_spec(_ts_spec)
with mock.patch.dict(sys.modules, {"ships_ahoy.matrix_driver": mock.MagicMock()}):
    _ts_spec.loader.exec_module(_ts_mod)

_display_event = _ts_mod._display_event
_show_idle = _ts_mod._show_idle
_handle_overflow = _ts_mod._handle_overflow
```

- [ ] **Step 5.2: Add shared fixtures**

Append after the existing `_import_build_parser` function (these imports must be at module level so all test functions can reference them):

```python
from datetime import datetime
from ships_ahoy.db import init_db, upsert_ship, write_event
from ships_ahoy.config import Config
from ships_ahoy.ship_tracker import ShipInfo


@pytest.fixture
def conn():
    c = init_db(":memory:")
    c.execute("UPDATE settings SET value='51.5' WHERE key='home_lat'")
    c.execute("UPDATE settings SET value='0.0' WHERE key='home_lon'")
    c.commit()
    return c


@pytest.fixture
def cfg(conn):
    return Config(conn)


@pytest.fixture
def driver():
    return mock.MagicMock()
```

- [ ] **Step 5.3: Add `test_display_event_scrolls_and_marks_displayed`**

```python
def test_display_event_scrolls_and_marks_displayed(conn, cfg, driver):
    """Event with matching ship → driver.scroll_text called, event marked displayed."""
    now = __import__("datetime").datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?,?,?,?)",
        (111222333, "MV Ticker", now, now),
    )
    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
        (111222333, "ARRIVED", "MV Ticker arrived", now),
    )
    conn.commit()

    event_row = conn.execute("SELECT * FROM events WHERE mmsi=111222333").fetchone()
    _display_event(conn, event_row, driver, cfg)

    driver.scroll_text.assert_called_once()
    updated = conn.execute(
        "SELECT displayed_at FROM events WHERE id=?", (event_row["id"],)
    ).fetchone()
    assert updated["displayed_at"] is not None
```

- [ ] **Step 5.4: Add `test_display_event_skips_missing_ship`**

```python
def test_display_event_skips_missing_ship(conn, cfg, driver):
    """Event for unknown MMSI → no scroll, event still marked displayed."""
    now = __import__("datetime").datetime.now().isoformat()
    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
        (999999999, "ARRIVED", "ghost ship", now),
    )
    conn.commit()

    event_row = conn.execute("SELECT * FROM events WHERE mmsi=999999999").fetchone()
    _display_event(conn, event_row, driver, cfg)

    driver.scroll_text.assert_not_called()
    updated = conn.execute(
        "SELECT displayed_at FROM events WHERE id=?", (event_row["id"],)
    ).fetchone()
    assert updated["displayed_at"] is not None
```

- [ ] **Step 5.5: Add `test_show_idle_with_home_uses_range_count`**

```python
def test_show_idle_with_home_uses_range_count(conn, cfg, driver):
    """With home set, idle message reflects ships within distance_km."""
    now = datetime.now().isoformat()
    # Insert 2 ships close to home (lat=51.5, lon=0.0)
    for mmsi, name in [(100000001, "MV Alpha"), (100000002, "MV Beta")]:
        conn.execute(
            "INSERT INTO ships (mmsi, name, latitude, longitude, last_seen, first_seen)"
            " VALUES (?,?,?,?,?,?)",
            (mmsi, name, 51.5, 0.0, now, now),
        )
    # Insert 1 ship far away
    conn.execute(
        "INSERT INTO ships (mmsi, name, latitude, longitude, last_seen, first_seen)"
        " VALUES (?,?,?,?,?,?)",
        (100000003, "MV Faraway", 0.0, 0.0, now, now),
    )
    conn.commit()

    _show_idle(conn, driver, cfg)

    call_args = driver.show_static.call_args[0]
    msg = call_args[0]
    assert "2" in msg
```

- [ ] **Step 5.6: Add `test_show_idle_without_home_uses_total_count`**

```python
def test_show_idle_without_home_uses_total_count(driver):
    """Without home location, idle message uses total ship count."""
    # Create a fresh connection with NO home_lat/lon set
    c = init_db(":memory:")
    cfg = Config(c)
    now = datetime.now().isoformat()
    for mmsi in [200000001, 200000002, 200000003]:
        c.execute(
            "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?,?,?,?)",
            (mmsi, f"Ship {mmsi}", now, now),
        )
    c.commit()

    _show_idle(c, driver, cfg)

    call_args = driver.show_static.call_args[0]
    msg = call_args[0]
    assert "3" in msg
```

- [ ] **Step 5.7: Add overflow tests**

```python
def test_handle_overflow_flushes_stale_events(conn, cfg, driver):
    """12 pending events with 11 older than 5 min → 11 flushed, summary scrolled."""
    old_time = "2020-01-01T00:00:00"
    now = __import__("datetime").datetime.now().isoformat()

    # Insert 11 stale events
    for i in range(11):
        conn.execute(
            "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
            (300000000 + i, "ARRIVED", "old event", old_time),
        )
    # Insert 1 fresh event
    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
        (300000099, "ARRIVED", "fresh event", now),
    )
    conn.commit()

    events = conn.execute(
        "SELECT * FROM events ORDER BY created_at ASC"
    ).fetchall()
    assert len(events) == 12

    _handle_overflow(conn, events, driver, cfg)

    # 11 stale events should now be marked displayed
    flushed = conn.execute(
        "SELECT COUNT(*) FROM events WHERE displayed_at IS NOT NULL"
    ).fetchone()[0]
    assert flushed == 11

    # Summary scroll message contains "flushed"
    call_args = driver.scroll_text.call_args[0]
    assert "flushed" in call_args[0]


def test_handle_overflow_displays_oldest_when_no_stale(conn, cfg, driver):
    """12 fresh events → _display_event called for events[0]."""
    now = __import__("datetime").datetime.now().isoformat()
    mmsi = 400000001

    # Insert ship so _display_event can find it
    conn.execute(
        "INSERT INTO ships (mmsi, name, last_seen, first_seen) VALUES (?,?,?,?)",
        (mmsi, "MV Overflow", now, now),
    )
    # Insert 12 fresh events all for the same MMSI
    for _ in range(12):
        conn.execute(
            "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?,?,?,?)",
            (mmsi, "ARRIVED", "event", now),
        )
    conn.commit()

    events = conn.execute(
        "SELECT * FROM events ORDER BY created_at ASC"
    ).fetchall()

    _handle_overflow(conn, events, driver, cfg)

    # driver.scroll_text called once (via _display_event for events[0])
    driver.scroll_text.assert_called_once()
    # The oldest event should be marked displayed
    oldest = conn.execute(
        "SELECT displayed_at FROM events WHERE id=?", (events[0]["id"],)
    ).fetchone()
    assert oldest["displayed_at"] is not None
```

- [ ] **Step 5.8: Run all ticker tests**

```bash
uv run pytest tests/test_ticker_service.py -v
```

Expected: all 8 tests pass (2 existing + 6 new).

- [ ] **Step 5.9: Commit**

```bash
git add tests/test_ticker_service.py
git commit -m "test: add integration tests for ticker_service"
```

---

### Task 6: Expand `tests/test_web_service.py`

**Files:**
- Modify: `tests/test_web_service.py`

**Key design note:** Modify the existing `client` fixture to yield `(flask_client, conn)` so tests can seed data. Update the two existing tests to unpack the tuple.

---

- [ ] **Step 6.1: Modify the `client` fixture to yield `(client, conn)`**

Replace the final `yield c` line of the existing fixture:

```python
# Before:
        with ws.app.test_client() as c:
            yield c

# After:
        with ws.app.test_client() as c:
            yield c, ws._conn
```

- [ ] **Step 6.2: Update the two existing tests to unpack the fixture**

```python
# Before:
def test_ticker_preview_content_type(client):
    resp = client.get("/ticker/preview", query_string={"_max_frames": "1"})
    ...

def test_ticker_preview_returns_data_line(client):
    ...
    resp = client.get("/ticker/preview", query_string={"_max_frames": "1"})
    ...

# After:
def test_ticker_preview_content_type(client):
    c, conn = client
    resp = c.get("/ticker/preview", query_string={"_max_frames": "1"})
    ...

def test_ticker_preview_returns_data_line(client):
    c, conn = client
    ...
    resp = c.get("/ticker/preview", query_string={"_max_frames": "1"})
    ...
```

- [ ] **Step 6.3: Run existing tests to confirm they still pass**

```bash
uv run pytest tests/test_web_service.py -v
```

Expected: both existing tests still pass.

- [ ] **Step 6.4: Add new web service tests**

Append to `tests/test_web_service.py`:

```python
from datetime import datetime
from ships_ahoy.db import upsert_ship
from ships_ahoy.ship_tracker import ShipInfo


def _make_ship(mmsi=123456789, name="MV Web Test"):
    return ShipInfo(mmsi=mmsi, name=name, last_seen=datetime.now())


def test_index_returns_200(client):
    c, conn = client
    resp = c.get("/")
    assert resp.status_code == 200


def test_index_shows_ship_name(client):
    c, conn = client
    upsert_ship(conn, _make_ship(name="MV Visible Ship"))
    resp = c.get("/")
    assert b"MV Visible Ship" in resp.data


def test_ship_detail_returns_200(client):
    c, conn = client
    upsert_ship(conn, _make_ship(mmsi=555000001))
    resp = c.get("/ship/555000001")
    assert resp.status_code == 200


def test_ship_detail_404_for_unknown(client):
    c, conn = client
    resp = c.get("/ship/9999999")
    assert resp.status_code == 404


def test_events_returns_200(client):
    c, conn = client
    resp = c.get("/events")
    assert resp.status_code == 200


def test_settings_get_returns_200(client):
    c, conn = client
    resp = c.get("/settings")
    assert resp.status_code == 200


def test_settings_post_saves_values(client):
    c, conn = client
    resp = c.post("/settings", data={"distance_km": "25.0"})
    assert resp.status_code == 302  # redirect

    from ships_ahoy.config import Config
    cfg = Config(conn)
    assert cfg.distance_km == 25.0


def test_settings_post_ignores_invalid_float(client):
    c, conn = client
    from ships_ahoy.config import Config
    original = Config(conn).distance_km

    resp = c.post("/settings", data={"distance_km": "notanumber"})
    assert resp.status_code == 302  # no crash

    assert Config(conn).distance_km == original
```

- [ ] **Step 6.5: Run all web service tests**

```bash
uv run pytest tests/test_web_service.py -v
```

Expected: all 10 tests pass (2 existing + 8 new).

- [ ] **Step 6.6: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6.7: Commit**

```bash
git add tests/test_web_service.py
git commit -m "test: add integration tests for web_service"
```
