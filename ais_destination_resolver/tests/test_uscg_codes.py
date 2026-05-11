import pytest
from pathlib import Path

from ais_destination_resolver.uscg_codes import translate_uscg_code, reload
from ais_destination_resolver.normalizer import normalize_destination


def test_translate_bare_code():
    assert translate_uscg_code("0TNR") == "Tennessee River"


def test_translate_prefixed_code():
    # CC-prefixed form produced by _extract_voyage_destination
    assert translate_uscg_code("US0TNR") == "Tennessee River"


def test_translate_origin_code():
    assert translate_uscg_code("0WF3") == "Wolf River"


def test_translate_unknown_code_returns_none():
    assert translate_uscg_code("ZZZZ") is None


def test_translate_is_case_insensitive():
    assert translate_uscg_code("0tnr") == "Tennessee River"
    assert translate_uscg_code("us0tnr") == "Tennessee River"


def test_normalize_voyage_field_translates_to_name():
    # Full pipeline: structured field → USCG code → plain name → normalized text
    assert normalize_destination("US^0WF3>0TNR") == "TENNESSEE RIVER"


def test_normalize_voyage_field_unknown_code_falls_back_to_locode():
    # If the dest code is not in the table, keep the raw LOCODE string
    assert normalize_destination("US^0WF3>ZZZZ") == "USZZZZ"


def test_reload_with_custom_csv(tmp_path):
    csv = tmp_path / "codes.csv"
    csv.write_text("code,name,waterway,notes\nTEST,Test Waterway,Test River,test\n")
    reload(csv)
    assert translate_uscg_code("TEST") == "Test Waterway"
    # Restore default
    reload()
