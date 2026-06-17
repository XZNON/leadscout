"""Offline tests for the extra discovery sources (JustDial / IndiaMART) — zero network.

Covers normalization + synthetic namespaced place_id, source tagging, in-source dedup,
cross-source phone dedup (Places canonical), the config-as-data toggle, and `_norm_phone` edges.
All via fixture clients; no live JustDial/IndiaMART fetch ever runs in pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from leadscout.clients import FixtureSourceClient, load_fixture_sources
from leadscout.models import GeographyInput, NicheSpec
from leadscout.stages.discover import _norm_phone, _raw_to_lead, discover

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _justdial() -> FixtureSourceClient:
    return FixtureSourceClient("justdial", FIXTURES / "justdial.json")


def _indiamart() -> FixtureSourceClient:
    return FixtureSourceClient("indiamart", FIXTURES / "indiamart.json")


def test_justdial_normalizes_with_namespaced_id(geo, niche) -> None:
    raws = _justdial().discover(geo, niche)
    lead = _raw_to_lead(raws[0], source="justdial")
    assert lead.source == "justdial"
    assert lead.place_id == "justdial:jd_neighbour"
    assert lead.name == "Neighbourhood Dental Care"
    assert lead.phone == "098450-67890"
    assert lead.website == "https://neighbourhooddental.example"
    assert lead.has_website is True
    assert lead.is_operational is True


def test_indiamart_normalizes_with_namespaced_id(geo, niche) -> None:
    raws = _indiamart().discover(geo, niche)
    lead = _raw_to_lead(raws[0], source="indiamart")
    assert lead.source == "indiamart"
    assert lead.place_id == "indiamart:im_dentalsupply"
    assert lead.name == "Bengaluru Dental Supplies Pvt Ltd"


def test_merge_dedups_colliding_phone_places_canonical(geo, niche, fixture_clients) -> None:
    places, _, _ = fixture_clients
    baseline = {x.place_id for x in discover(geo, niche, places)}
    merged = discover(geo, niche, places, extra_sources=[_justdial()])
    ids = {x.place_id for x in merged}

    # jd_bright_dup shares p_bright's phone → dropped; the two non-colliding listings are added.
    assert "justdial:jd_bright_dup" not in ids
    assert "justdial:jd_neighbour" in ids
    assert "justdial:jd_smileworks" in ids
    assert ids == baseline | {"justdial:jd_neighbour", "justdial:jd_smileworks"}

    # The surviving row for the shared phone is the Google Places record.
    bright = next(x for x in merged if x.place_id == "p_bright")
    assert bright.source == "google_places"


def test_in_source_dedup_collapses_duplicate_place_id(geo, niche, fixture_clients) -> None:
    places, _, _ = fixture_clients
    dup = FixtureSourceClient("justdial", FIXTURES / "justdial.json")
    # Two identical listing dicts → same synthetic place_id → one row.
    dup._data = [dup._data[0], dict(dup._data[0])]
    merged = discover(geo, niche, places, extra_sources=[dup])
    ids = [x.place_id for x in merged]
    assert ids.count("justdial:jd_neighbour") == 1


def test_toggle_off_is_byte_identical(geo, niche, fixture_clients) -> None:
    places, _, _ = fixture_clients
    assert discover(geo, niche, places) == discover(geo, niche, places, extra_sources=[])


def test_toggle_on_grows_by_non_colliding(geo, niche, fixture_clients) -> None:
    places, _, _ = fixture_clients
    base = len(discover(geo, niche, places))
    grown = len(discover(geo, niche, places, extra_sources=[_justdial(), _indiamart()]))
    # +2 from JustDial (one collides), +1 from IndiaMART.
    assert grown == base + 3


def test_load_fixture_sources_skips_places(geo, niche) -> None:
    built = load_fixture_sources(FIXTURES, ["google_places", "justdial", "indiamart"])
    assert [c.source_name for c in built] == ["justdial", "indiamart"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+91 98765 43210", "9876543210"),
        ("098765-43210", "9876543210"),
        ("12345", None),
        ("", None),
        (None, None),
    ],
)
def test_norm_phone_edges(raw, expected) -> None:
    assert _norm_phone(raw) == expected


def test_bad_source_value_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NicheSpec(keywords=["dentist"], sources=["yelp"])  # type: ignore[list-item]


def test_geography_input_used_by_fixture_is_consumed(niche) -> None:
    # Sanity: city geography flows in without needing Places tiling for extra sources.
    g = GeographyInput(city="Bengaluru")
    assert _justdial().discover(g, niche)
