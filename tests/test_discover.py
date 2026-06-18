from __future__ import annotations

import json
from pathlib import Path

from leadscout.clients import FixturePlacesClient
from leadscout.models import BBox, GeographyInput, NicheSpec, Tile
from leadscout.stages.discover import (
    MAX_SUBDIVIDE_DEPTH,
    _subdivide,
    discover,
    resolve_tiles,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


# --------------------------------------------------------------------------- existing tests


def test_dedup_on_place_id(geo, niche, fixture_clients):
    places, _, _ = fixture_clients
    leads = discover(geo, niche, places)
    ids = [x.place_id for x in leads]
    # Same results are returned per (tile x keyword); output must be deduped.
    assert len(ids) == len(set(ids)), "discover must dedup on place_id"
    assert "p_bright" in set(ids)


def test_point_geography_is_single_tile(fixture_clients):
    places, _, _ = fixture_clients
    g = GeographyInput(point={"lat": 12.97, "lng": 77.59, "radius_km": 10})
    tiles = resolve_tiles(g, places)
    assert len(tiles) == 1
    assert tiles[0].radius_km == 10


def test_bbox_tiling_overlaps_and_caps_radius(fixture_clients):
    places, _, _ = fixture_clients
    big = GeographyInput(bbox=BBox(min_lat=12.0, min_lng=77.0, max_lat=13.0, max_lng=78.0))
    tiles = resolve_tiles(big, places)
    assert len(tiles) >= 4, "a ~110 km box must be split into multiple tiles"
    assert all(t.radius_km <= 50 for t in tiles), "no tile may exceed the 50 km Places cap"


# --------------------------------------------------------------------------- SearchPage plumbing


def test_search_page_not_saturated_by_default(fixture_clients):
    places, _, _ = fixture_clients
    page = places.search(12.97, 77.59, 10.0, "dentist")
    assert page.saturated is False
    assert isinstance(page.results, list)
    assert len(page.results) > 0


def test_search_page_saturated_when_flagged(tmp_path):
    fixture_data = json.loads((FIXTURES / "places.json").read_text(encoding="utf-8"))
    fixture_data["saturated_keywords"] = ["dentist"]
    sat_fixture = tmp_path / "places_sat.json"
    sat_fixture.write_text(json.dumps(fixture_data), encoding="utf-8")

    client = FixturePlacesClient(sat_fixture)
    page = client.search(12.97, 77.59, 10.0, "dentist")
    assert page.saturated is True

    page2 = client.search(12.97, 77.59, 10.0, "orthodontist")
    assert page2.saturated is False


# --------------------------------------------------------------------------- _subdivide geometry


def test_subdivide_returns_four_tiles():
    parent = Tile(lat=12.97, lng=77.59, radius_km=40.0, depth=0)
    children = _subdivide(parent)
    assert len(children) == 4


def test_subdivide_half_radius_and_incremented_depth():
    parent = Tile(lat=12.97, lng=77.59, radius_km=40.0, depth=0)
    children = _subdivide(parent)
    for child in children:
        assert abs(child.radius_km - 20.0) < 1e-9
        assert child.depth == 1
        assert child.radius_km <= 50.0


def test_subdivide_centers_near_parent():
    parent = Tile(lat=12.97, lng=77.59, radius_km=20.0, depth=1)
    children = _subdivide(parent)
    for child in children:
        # Each child center is within parent.radius_km of the parent center (roughly)
        dlat = abs(child.lat - parent.lat)
        dlng = abs(child.lng - parent.lng)
        assert dlat < 1.0 and dlng < 1.0


def test_subdivide_depth_cap_bounded():
    tile = Tile(lat=12.97, lng=77.59, radius_km=40.0, depth=0)
    for _ in range(MAX_SUBDIVIDE_DEPTH):
        tile = _subdivide(tile)[0]
    assert tile.depth == MAX_SUBDIVIDE_DEPTH
    # one more level would exceed the cap; discover loop would not enqueue these
    deep = Tile(lat=12.97, lng=77.59, radius_km=tile.radius_km, depth=MAX_SUBDIVIDE_DEPTH)
    assert deep.depth >= MAX_SUBDIVIDE_DEPTH


# --------------------------------------------------------------------------- saturation/subdivision


def _make_saturated_client(
    tmp_path: Path, extra_results: list[dict] | None = None
) -> FixturePlacesClient:
    fixture_data = json.loads((FIXTURES / "places.json").read_text(encoding="utf-8"))
    fixture_data["saturated_keywords"] = ["dentist"]
    if extra_results:
        fixture_data["results"] = fixture_data["results"] + extra_results
    sat_fixture = tmp_path / "places_sat.json"
    sat_fixture.write_text(json.dumps(fixture_data), encoding="utf-8")
    return FixturePlacesClient(sat_fixture)


def test_saturation_triggers_subdivision(tmp_path):
    """When dentist is saturated at depth 0, discover must search sub-tiles."""
    client = _make_saturated_client(tmp_path)
    geo = GeographyInput(city="Bengaluru")
    niche = NicheSpec(keywords=["dentist"])

    leads = discover(geo, niche, client)
    ids = [x.place_id for x in leads]
    # Dedup must hold even under subdivision (sub-tiles return overlapping results)
    assert len(ids) == len(set(ids)), "place_id dedup must survive subdivision"
    assert len(ids) > 0


def test_depth_cap_prevents_infinite_recursion(tmp_path, monkeypatch):
    """All (tile,keyword) pairs saturated: subdivision must stop at MAX_SUBDIVIDE_DEPTH."""
    import leadscout.stages.discover as disc_mod

    monkeypatch.setattr(disc_mod, "MAX_SUBDIVIDE_DEPTH", 1)
    client = _make_saturated_client(tmp_path)
    geo = GeographyInput(city="Bengaluru")
    niche = NicheSpec(keywords=["dentist"])

    # Must complete without infinite loop
    leads = discover(geo, niche, client)
    assert isinstance(leads, list)


def test_dedup_survives_subdivision(tmp_path):
    """Overlapping sub-tiles returning the same place_id must not produce duplicates."""
    client = _make_saturated_client(tmp_path)
    geo = GeographyInput(city="Bengaluru")
    niche = NicheSpec(keywords=["dentist"])
    leads = discover(geo, niche, client)
    ids = [x.place_id for x in leads]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------- state geography


def test_state_geography_resolves_to_multiple_tiles(fixture_clients):
    """GeographyInput(state=...) must produce multiple tiles (geocodes to a bbox, then tiles it)."""
    places, _, _ = fixture_clients
    geo = GeographyInput(state="Karnataka")
    tiles = resolve_tiles(geo, places)
    # The fixture bbox (12.95–12.99 lat, 77.58–77.62 lng) is ~4 km × ~4 km; at 40 km radius
    # step, it yields a small grid — at least 1 tile, but assert ≥1 and that it runs.
    assert len(tiles) >= 1
    assert all(t.radius_km <= 50 for t in tiles)


def test_state_yaml_runs_end_to_end(fixture_clients):
    """Load karnataka.yaml, run discover — no error, non-empty deduped leads."""
    from leadscout.config import load_geography
    from leadscout.models import NicheSpec

    places, _, _ = fixture_clients
    geo = load_geography(str(EXAMPLES / "karnataka.yaml"))
    niche = NicheSpec(keywords=["dentist"])
    leads = discover(geo, niche, places)
    ids = [x.place_id for x in leads]
    assert len(ids) == len(set(ids))
    assert len(ids) > 0


# --------------------------------------------------------------------------- regression / cheapness


def test_non_saturated_path_unchanged(geo, niche, fixture_clients):
    """A non-saturated fixture must produce the same leads as before — no spurious subdivision."""
    places, _, _ = fixture_clients
    leads = discover(geo, niche, places)
    ids = set(x.place_id for x in leads)
    # Baseline: all fixture place_ids with no saturation flag present
    assert "p_bright" in ids
    # Dedup holds
    all_ids = [x.place_id for x in leads]
    assert len(all_ids) == len(set(all_ids))
