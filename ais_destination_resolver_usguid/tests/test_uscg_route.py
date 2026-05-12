from ais_destination_resolver.uscg_route import parse_ais_route


def test_parse_guid_route_inherits_us_prefix():
    route = parse_ais_route("Us^084Y>0Wqb")

    assert route.separator == ">"
    assert route.route_type == "origin_to_destination"
    assert [token.normalized for token in route.tokens] == ["US^084Y", "US^0WQB"]
    assert [token.token_type for token in route.tokens] == ["us_guid", "us_guid"]


def test_parse_unlocode_area_route():
    route = parse_ais_route("Uscir<>Uscir")

    assert route.separator == "<>"
    assert route.route_type == "operating_within_area"
    assert [token.normalized for token in route.tokens] == ["USCIR", "USCIR"]
    assert [token.token_type for token in route.tokens] == ["unlocode", "unlocode"]
