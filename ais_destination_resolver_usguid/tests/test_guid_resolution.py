from ais_destination_resolver.models import Destination, GuidLocation
from ais_destination_resolver.resolver import DestinationResolver


def test_resolve_guid_route_with_imported_guid_locations():
    resolver = DestinationResolver(
        destinations=[],
        guid_locations=[
            GuidLocation(
                id=1,
                guid="084Y",
                full_code="US^084Y",
                unlocode=None,
                official_name="Origin Facility",
                port_name="St. Louis",
                waterway_name="Mississippi River",
                facility_type="Dock",
                latitude=38.6,
                longitude=-90.2,
                mile=180.0,
                source="test",
                source_updated=None,
                notes=None,
            ),
            GuidLocation(
                id=2,
                guid="0WQB",
                full_code="US^0WQB",
                unlocode=None,
                official_name="Destination Facility",
                port_name="Paducah",
                waterway_name="Ohio River",
                facility_type="Dock",
                latitude=37.0,
                longitude=-88.6,
                mile=934.0,
                source="test",
                source_updated=None,
                notes=None,
            ),
        ],
    )

    route = resolver.resolve_route("US^084Y>0WQB")

    assert route.confidence == 1.0
    assert route.endpoints[0].guid_location.official_name == "Origin Facility"
    assert route.endpoints[1].guid_location.official_name == "Destination Facility"


def test_resolve_unlocode_route_falls_back_to_destination_dictionary():
    cairo = Destination(
        id=1,
        locode="USCIR",
        canonical_name="Cairo",
        aliases=["CAIRO IL"],
        state="IL",
        country_code="US",
        waterway="Ohio/Mississippi River",
        river_mile=None,
        latitude=37.0053,
        longitude=-89.1765,
        destination_type="riverport",
        status="seed",
        source="test",
        source_updated=None,
        is_active=True,
        notes=None,
    )
    resolver = DestinationResolver([cairo])

    route = resolver.resolve_route("USCIR<>USCIR")

    assert route.route_type == "operating_within_area"
    assert route.endpoints[0].destination.canonical_name == "Cairo"
    assert route.endpoints[1].destination.canonical_name == "Cairo"
