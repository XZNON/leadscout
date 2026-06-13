"""Stage 1 — DISCOVER. Geography -> tiles -> (tile x keyword) search -> dedup(place_id).

Deterministic, zero LLM. Handles the Places reality (idea.md §7/§10): ~60 results/query and a
~50 km radius cap mean we must tile the area and dedup, because tiles and keywords overlap.
"""

from __future__ import annotations

import math

from ..clients import PlacesClient
from ..models import BBox, GeographyInput, Lead, NicheSpec, Point, Tile

PLACES_RADIUS_CAP_KM = 50.0
_DEFAULT_TILE_RADIUS_KM = 40.0  # overlap headroom under the 50 km cap
_KM_PER_DEG_LAT = 111.0


def resolve_tiles(geo: GeographyInput, client: PlacesClient) -> list[Tile]:
    """Turn any GeographyInput into a list of <=50 km circular tiles."""
    if geo.point is not None:
        p: Point = geo.point
        return [Tile(lat=p.lat, lng=p.lng, radius_km=min(p.radius_km, PLACES_RADIUS_CAP_KM))]

    if geo.bbox is not None:
        return _tile_bbox(geo.bbox)

    # city / state -> geocode to a bbox -> tile it
    query = geo.city or geo.state or ""
    bbox = client.geocode_bbox(query)
    return _tile_bbox(bbox)


def _tile_bbox(bbox: BBox, radius_km: float = _DEFAULT_TILE_RADIUS_KM) -> list[Tile]:
    """Cover a bbox with a grid of overlapping circular tiles.

    Spacing = radius (not diameter) so adjacent circles overlap — corners stay covered. The
    overlap is exactly why dedup-on-place_id is mandatory downstream.
    """
    mid_lat = (bbox.min_lat + bbox.max_lat) / 2
    km_per_deg_lng = _KM_PER_DEG_LAT * max(math.cos(math.radians(mid_lat)), 0.01)

    step_lat = radius_km / _KM_PER_DEG_LAT
    step_lng = radius_km / km_per_deg_lng

    tiles: list[Tile] = []
    lat = bbox.min_lat
    while lat <= bbox.max_lat + step_lat:
        lng = bbox.min_lng
        while lng <= bbox.max_lng + step_lng:
            tiles.append(Tile(lat=round(lat, 6), lng=round(lng, 6), radius_km=radius_km))
            lng += step_lng
        lat += step_lat
    return tiles or [Tile(lat=mid_lat, lng=(bbox.min_lng + bbox.max_lng) / 2, radius_km=radius_km)]


def _raw_to_lead(raw: dict) -> Lead:
    """Normalize a raw Places result into the common Lead shape."""
    website = raw.get("website") or raw.get("websiteUri")
    return Lead(
        place_id=raw["place_id"],
        name=raw.get("name", raw.get("displayName", "")) or "",
        source="google_places",
        category=raw.get("category") or raw.get("primaryType"),
        place_type=raw.get("place_type") or raw.get("primaryType"),
        address=raw.get("address") or raw.get("formattedAddress"),
        city=raw.get("city"),
        state=raw.get("state"),
        phone=raw.get("phone") or raw.get("internationalPhoneNumber"),
        website=website,
        rating=raw.get("rating"),
        review_count=raw.get("review_count") or raw.get("userRatingCount"),
        has_website=bool(website),
        is_operational=raw.get("is_operational", raw.get("businessStatus") != "CLOSED_PERMANENTLY"),
        reviews=list(raw.get("reviews", [])),
    )


def discover(geo: GeographyInput, niche: NicheSpec, client: PlacesClient) -> list[Lead]:
    """Run the full discovery loop and return leads deduped on place_id."""
    tiles = resolve_tiles(geo, client)
    by_id: dict[str, Lead] = {}
    for tile in tiles:
        for keyword in niche.keywords:
            for raw in client.search(tile.lat, tile.lng, tile.radius_km, keyword):
                pid = raw.get("place_id")
                if not pid:
                    continue
                if pid not in by_id:  # dedup on place_id — mandatory (idea.md §10)
                    by_id[pid] = _raw_to_lead(raw)
    return list(by_id.values())
