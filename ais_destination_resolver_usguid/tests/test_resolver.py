from ais_destination_resolver.resolver import DestinationResolver
from ais_destination_resolver.seeds import load_seed_destinations


def test_exact_alias_match():
    resolver = DestinationResolver(load_seed_destinations())
    match = resolver.resolve("NOLA")
    assert match.destination is not None
    assert match.destination.canonical_name == "New Orleans"
    assert match.match_method == "exact_alias"


def test_fuzzy_match():
    resolver = DestinationResolver(load_seed_destinations())
    match = resolver.resolve("Paduca")
    assert match.destination is not None
    assert match.destination.canonical_name == "Paducah"
    assert match.confidence >= 0.65
