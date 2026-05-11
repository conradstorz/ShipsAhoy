from ais_destination_resolver.normalizer import normalize_destination, _extract_voyage_destination


def test_normalizes_noisy_destination_text():
    assert normalize_destination("To: N.O.L.A.") == "N O L A"
    assert normalize_destination(" for Paducah, KY ") == "PADUCAH KY"


def test_extract_voyage_destination():
    assert _extract_voyage_destination("US^0WF3>0TNR") == "US0TNR"
    assert _extract_voyage_destination("US^0WF3>0TNR ") == "US0TNR"  # trailing space
    assert _extract_voyage_destination("us^0wf3>0tnr") == "US0TNR"  # lowercase
    assert _extract_voyage_destination("NOLA") is None
    assert _extract_voyage_destination("") is None


def test_normalize_destination_structured_voyage():
    # CC^ORIGIN>DEST format: known USCG code translates to plain-text name
    assert normalize_destination("US^0WF3>0TNR") == "TENNESSEE RIVER"
    assert normalize_destination("us^0wf3>0tnr") == "TENNESSEE RIVER"
