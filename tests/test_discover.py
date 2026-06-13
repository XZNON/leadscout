from __future__ import annotations

from leadscout.models import BBox, GeographyInput
from leadscout.stages.discover import discover, resolve_tiles


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
