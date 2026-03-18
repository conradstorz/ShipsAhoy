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
    """Successful scrape -> enrichment row saved, ENRICHED event written."""
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
    """All scrapers fail -> fetch_attempts incremented, no ENRICHED event."""
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
