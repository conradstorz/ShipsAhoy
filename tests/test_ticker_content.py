"""Tests for ships_ahoy.ticker_content."""
import pytest
from ships_ahoy.config import Config
from ships_ahoy.db import init_db, add_quip
from ships_ahoy.ticker_content import build_idle_chunks, build_playlist, build_ship_chunks


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
    assert any("MV Test" in text for text, _, _ in playlist)


def test_build_playlist_returns_idle_when_no_ships(conn):
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    assert playlist[0][0] == "No ships in range"
    assert playlist[0][1] == ()
    assert playlist[0][2] == ()


def test_build_playlist_orders_closest_first(conn):
    _make_ship(conn, mmsi=200000002, name="MV Far",   latitude=51.9, longitude=0.1)
    _make_ship(conn, mmsi=200000003, name="MV Close", latitude=51.51, longitude=0.1)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    close_idx = next(i for i, (text, _, _) in enumerate(playlist) if "MV Close" in text)
    far_idx   = next(i for i, (text, _, _) in enumerate(playlist) if "MV Far" in text)
    assert close_idx < far_idx


def test_build_playlist_returns_idle_when_home_not_set(conn):
    conn.execute("UPDATE settings SET value=NULL WHERE key='home_lat'")
    conn.execute("UPDATE settings SET value=NULL WHERE key='home_lon'")
    conn.commit()
    _make_ship(conn, mmsi=200000004)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    assert playlist[0][0] == "No ships in range"


def test_build_playlist_each_entry_is_3_tuple(conn):
    _make_ship(conn, mmsi=200000005, latitude=51.5, longitude=0.1)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    for entry in playlist:
        assert isinstance(entry, tuple) and len(entry) == 3
        text, mmsis, event_ids = entry
        assert isinstance(text, str)
        assert isinstance(mmsis, tuple)
        assert isinstance(event_ids, tuple)


def test_build_playlist_groups_stationary_ships(conn):
    _make_ship(conn, mmsi=200000006, name="MV Anchor", latitude=51.5, longitude=0.1, status=1, speed=0.0)
    _make_ship(conn, mmsi=200000007, name="MV Moored", latitude=51.5, longitude=0.1, status=5, speed=0.0)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    anchor_entries = [(text, mmsis) for text, mmsis, _ in playlist if text.startswith("At anchor:")]
    assert len(anchor_entries) == 1
    text, mmsis = anchor_entries[0]
    assert "MV Anchor" in text
    assert "MV Moored" in text
    assert 200000006 in mmsis
    assert 200000007 in mmsis


def test_build_playlist_stationary_entry_at_end(conn):
    _make_ship(conn, mmsi=200000008, name="MV Moving", latitude=51.5, longitude=0.1, status=0, speed=8.5)
    _make_ship(conn, mmsi=200000009, name="MV Still",  latitude=51.5, longitude=0.1, status=1, speed=0.0)
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    last_text, _, _ = playlist[-1]
    assert last_text.startswith("At anchor:")


def test_build_playlist_prioritises_never_shown(conn):
    """A ship with ticker_shown_at=NULL appears before one that was shown."""
    import datetime
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    _make_ship(conn, mmsi=200000010, name="MV Shown",   latitude=51.5, longitude=0.1, speed=5.0)
    _make_ship(conn, mmsi=200000011, name="MV Unshown", latitude=51.5, longitude=0.1, speed=5.0)
    conn.execute("UPDATE ships SET ticker_shown_at=? WHERE mmsi=200000010", (old_time,))
    conn.commit()
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    unshown_idx = next(i for i, (text, _, _) in enumerate(playlist) if "MV Unshown" in text)
    shown_idx   = next(i for i, (text, _, _) in enumerate(playlist) if "MV Shown" in text)
    assert unshown_idx < shown_idx


def test_build_playlist_prepends_pending_events(conn):
    """Pending events appear before ship info chunks."""
    from ships_ahoy.db import write_event
    from ships_ahoy.events import EventType
    _make_ship(conn, mmsi=200000012, name="MV Event", latitude=51.5, longitude=0.1, speed=5.0)
    write_event(conn, 200000012, EventType.ARRIVED, "MV Event arrived")
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    # First entry should be the event (event_ids non-empty), ship chunks follow
    event_entries = [(i, text, ev) for i, (text, _, ev) in enumerate(playlist) if ev]
    ship_entries  = [(i, text) for i, (text, mmsis, ev) in enumerate(playlist)
                     if not ev and mmsis]
    assert event_entries, "expected at least one event entry"
    assert ship_entries,  "expected at least one ship entry"
    assert event_entries[0][0] < ship_entries[0][0], "events must precede ship chunks"


def test_build_playlist_shows_events_when_no_ships_in_range(conn):
    """Events are shown even when no ships are currently in range."""
    from ships_ahoy.db import write_event
    from ships_ahoy.events import EventType
    # Ship outside the range circle so get_in_range_ships_with_distance returns []
    _make_ship(conn, mmsi=200000013, name="MV Far Away", latitude=0.0, longitude=0.0, speed=5.0)
    write_event(conn, 200000013, EventType.DEPARTED, "MV Far Away departed")
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    # Should not fall back to idle — should contain the DEPARTED event
    assert playlist[0][0] != "No ships in range"
    assert any("departed" in text.lower() for text, _, _ in playlist)


def test_arrived_event_unnamed_ship_deferred_when_recent(conn):
    """ARRIVED event for an unnamed brand-new ship is not shown until 5 min have passed."""
    from ships_ahoy.db import write_event
    from ships_ahoy.events import EventType
    _make_ship(conn, mmsi=200000030, name=None, latitude=51.5, longitude=0.1,
               speed=5.0, visit_count=1)
    write_event(conn, 200000030, EventType.ARRIVED, "200000030 arrived")
    # created_at is effectively now — should be deferred
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    event_entries = [ev for _, _, ev in playlist if ev]
    assert not event_entries, "unnamed recent ARRIVED should be deferred, not shown"


def test_arrived_event_unnamed_ship_shown_after_timeout(conn):
    """ARRIVED event for an unnamed ship older than 5 min is shown as unidentified."""
    import datetime as _dt
    from ships_ahoy.db import write_event
    from ships_ahoy.events import EventType
    _make_ship(conn, mmsi=200000031, name=None, latitude=51.5, longitude=0.1,
               speed=5.0, visit_count=1)
    write_event(conn, 200000031, EventType.ARRIVED, "200000031 arrived")
    old_ts = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=10)).isoformat()
    conn.execute("UPDATE events SET created_at=? WHERE mmsi=200000031", (old_ts,))
    conn.commit()
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    event_entries = [(text, ev) for text, _, ev in playlist if ev]
    assert event_entries, "unnamed stale ARRIVED should be shown after timeout"
    assert any("unidentified" in text for text, _ in event_entries)


def test_arrived_event_named_ship_shown_immediately(conn):
    """ARRIVED event for a named ship is shown immediately without any deferral."""
    from ships_ahoy.db import write_event
    from ships_ahoy.events import EventType
    _make_ship(conn, mmsi=200000032, name="MV Known", latitude=51.5, longitude=0.1,
               speed=5.0, visit_count=1)
    write_event(conn, 200000032, EventType.ARRIVED, "MV Known arrived")
    cfg = Config(conn)
    playlist = build_playlist(conn, cfg)
    event_entries = [(text, ev) for text, _, ev in playlist if ev]
    assert event_entries, "named ARRIVED should be shown immediately"
    assert any("MV Known" in text for text, _ in event_entries)
