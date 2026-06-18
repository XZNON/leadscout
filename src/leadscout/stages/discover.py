"""Stage 1 — DISCOVER. Geography -> tiles -> (tile x keyword) search -> dedup(place_id).

Deterministic, zero LLM. Handles the Places reality (idea.md §7/§10): ~60 results/query and a
~50 km radius cap mean we must tile the area and dedup, because tiles and keywords overlap.
"""

from __future__ import annotations

import logging
import math
from collections import deque

from ..clients import PlacesClient, SourceClient
from ..models import BBox, GeographyInput, Lead, NicheSpec, Point, Source, Tile

logger = logging.getLogger(__name__)

PLACES_RADIUS_CAP_KM = 50.0
_DEFAULT_TILE_RADIUS_KM = 40.0  # overlap headroom under the 50 km cap
_KM_PER_DEG_LAT = 111.0
MAX_SUBDIVIDE_DEPTH = 2   # at most 4**2 = 16 sub-tiles per saturated top tile
MAX_TILES = 2000          # hard safety ceiling on total (tile, keyword) searches per run


def resolve_tiles(geo: GeographyInput, client: PlacesClient) -> list[Tile]:
    """Turn any GeographyInput into a list of <=50 km circular tiles.

    Produces the initial grid only. Saturation-driven subdivision is handled in
    discover.discover's search loop, where per-(tile,keyword) results are actually visible.
    """
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


def _subdivide(tile: Tile) -> list[Tile]:
    """Split one tile into 4 overlapping quadrant sub-tiles at half the parent radius.

    Centers are offset by half the parent radius in each cardinal direction, using the same
    lat/lng-per-km math as _tile_bbox. Child radius is parent/2; stays under the 50 km cap since
    _DEFAULT_TILE_RADIUS_KM (40 km) → 20 km → 10 km, all well below PLACES_RADIUS_CAP_KM.
    """
    r = tile.radius_km / 2
    km_per_deg_lng = _KM_PER_DEG_LAT * max(math.cos(math.radians(tile.lat)), 0.01)
    d_lat = r / _KM_PER_DEG_LAT
    d_lng = r / km_per_deg_lng
    child_depth = tile.depth + 1
    def _t(lat: float, lng: float) -> Tile:
        return Tile(lat=round(lat, 6), lng=round(lng, 6), radius_km=r, depth=child_depth)

    return [
        _t(tile.lat + d_lat, tile.lng + d_lng),
        _t(tile.lat + d_lat, tile.lng - d_lng),
        _t(tile.lat - d_lat, tile.lng + d_lng),
        _t(tile.lat - d_lat, tile.lng - d_lng),
    ]


def _norm_phone(s: str | None) -> str | None:
    """Last-10-digits phone key for cross-source dedup. `None` if <10 digits (no key)."""
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else None


def _raw_to_lead(raw: dict, source: Source = "google_places") -> Lead:
    """Normalize a raw source result into the common Lead shape.

    Places carry a real `place_id`; other directories have none, so we synthesize a namespaced,
    collision-free id (`f"{source}:{listing_id}"`) — still a `str`, the `Lead.place_id` contract is
    intact. The field-aliasing below already spans both Places (`websiteUri`/`internationalPhone…`)
    and the plain directory keys, so this stays the single normalization choke point.
    """
    website = raw.get("website") or raw.get("websiteUri")
    place_id = raw["place_id"] if source == "google_places" else f"{source}:{raw['listing_id']}"
    return Lead(
        place_id=place_id,
        name=raw.get("name", raw.get("displayName", "")) or "",
        source=source,
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


def discover(
    geo: GeographyInput,
    niche: NicheSpec,
    client: PlacesClient,
    extra_sources: list[SourceClient] | None = None,
) -> list[Lead]:
    """Run the full discovery loop and return leads deduped on place_id.

    Google Places is canonical and collected first (tiling unchanged). Extra directory sources
    (JustDial/IndiaMART) are merged after, into the SAME `by_id` dedup, with two gates: (a) skip a
    duplicate `place_id` (in-source dedup, unchanged); (b) skip a lead whose normalized phone is
    already held (cross-source dedup — earlier/Places record wins). Phone-less leads fall back to
    place_id only (no cross-source merge); Stage 2 drops them anyway. Default `extra_sources` is
    empty, so existing Places-only callers are byte-identical (idea.md §10).
    """
    tiles = resolve_tiles(geo, client)
    logger.debug("Initial tile grid: %d tiles for %d keywords.", len(tiles), len(niche.keywords))
    by_id: dict[str, Lead] = {}
    seen_phones: dict[str, str] = {}  # norm_phone -> owning place_id (first wins, Places canonical)

    def _claim_phone(lead: Lead) -> None:
        np = _norm_phone(lead.phone)
        if np and np not in seen_phones:
            seen_phones[np] = lead.place_id

    work: deque[tuple[Tile, str]] = deque(
        (tile, kw) for tile in tiles for kw in niche.keywords
    )
    searches_done = 0
    while work:
        if searches_done >= MAX_TILES:
            logger.warning(
                "MAX_TILES=%d reached; stopping further (tile,keyword) searches.", MAX_TILES
            )
            break
        tile, keyword = work.popleft()
        page = client.search(tile.lat, tile.lng, tile.radius_km, keyword)
        searches_done += 1
        for raw in page.results:
            pid = raw.get("place_id")
            if not pid:
                continue
            if pid not in by_id:  # dedup on place_id — mandatory (idea.md §10)
                lead = _raw_to_lead(raw)
                by_id[pid] = lead
                _claim_phone(lead)
        if page.saturated and tile.depth < MAX_SUBDIVIDE_DEPTH:
            for sub_tile in _subdivide(tile):
                work.append((sub_tile, keyword))

    for source in extra_sources or []:
        for raw in source.discover(geo, niche):
            lead = _raw_to_lead(raw, source=source.source_name)
            if lead.place_id in by_id:
                continue  # in-source / namespaced-id dedup
            if (np := _norm_phone(lead.phone)) is not None and np in seen_phones:
                continue  # cross-source phone collision — canonical record already kept
            by_id[lead.place_id] = lead
            _claim_phone(lead)

    return list(by_id.values())
