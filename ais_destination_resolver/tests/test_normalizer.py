from ais_destination_resolver.normalizer import normalize_destination


def test_normalizes_noisy_destination_text():
    assert normalize_destination("To: N.O.L.A.") == "N O L A"
    assert normalize_destination(" for Paducah, KY ") == "PADUCAH KY"
