"""Typed I/O contracts for the four pipeline stages.

These pydantic models are the contracts between stages. A stage takes one of these and
returns one of these; that is the whole interface. Keep them stable — changing a shape is a
cross-stage change.
"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, Field, model_validator

Source = Literal["google_places", "justdial", "indiamart"]
LeadState = Literal["new", "seen", "contacted"]


# --------------------------------------------------------------------------- inputs


class Point(BaseModel):
    lat: float
    lng: float
    radius_km: float = Field(gt=0, le=50)  # Places radius cap is ~50 km (idea.md §10)


class BBox(BaseModel):
    min_lat: float
    min_lng: float
    max_lat: float
    max_lng: float


class GeographyInput(BaseModel):
    """One of: point+radius, named city/state, or an explicit bbox. Resolved into tiles."""

    point: Point | None = None
    city: str | None = None
    state: str | None = None
    bbox: BBox | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> GeographyInput:
        provided = [self.point, self.city, self.state, self.bbox]
        if sum(x is not None for x in provided) != 1:
            raise ValueError("GeographyInput needs exactly one of: point, city, state, bbox")
        return self


class NicheSpec(BaseModel):
    keywords: list[str] = Field(min_length=1)
    place_type_allowlist: list[str] = Field(default_factory=list)
    # Which discovery directories cover this vertical/geography. Config-as-data: enabling a source
    # is a YAML edit, no code change. Default is Places-only so existing runs are unchanged. Entries
    # are validated against the Source literal (a typo'd source raises at load).
    sources: list[Source] = Field(default_factory=lambda: cast("list[Source]", ["google_places"]))


class SizeProxy(BaseModel):
    review_count: dict[str, int] = Field(default_factory=lambda: {"min": 0, "max": 10_000})

    @property
    def min(self) -> int:
        return int(self.review_count.get("min", 0))

    @property
    def max(self) -> int:
        return int(self.review_count.get("max", 10_000))


class ICPSpec(BaseModel):
    """The heart of the system: one product = one ICP file (idea.md §6.3)."""

    product: str
    buyer: str
    pain_signals: list[str] = Field(default_factory=list)
    size_proxy: SizeProxy = Field(default_factory=SizeProxy)
    disqualifiers: list[str] = Field(default_factory=list)
    # Stage 2 inputs (idea.md §7 / Step 4):
    require_website: bool = True
    # Contactability bar before spending LLM tokens. "phone_or_named_email" = direct phone OR a
    # named-owner email; "phone" = phone required; "any" = phone OR any email.
    contactability: Literal["phone_or_named_email", "phone", "any"] = "phone_or_named_email"


# --------------------------------------------------------------------------- tiles


class Tile(BaseModel):
    """A single circular search area (<= 50 km) the discovery loop queries per keyword."""

    lat: float
    lng: float
    radius_km: float = Field(gt=0, le=50)
    depth: int = 0  # subdivision depth; 0 = top-level tile from initial grid


class SearchPage(BaseModel):
    """Return value of PlacesClient.search — results plus a saturation signal."""

    results: list[dict] = Field(default_factory=list)
    saturated: bool = False  # True when the ~60-result/3-page cap was hit with more available


# --------------------------------------------------------------------------- the Lead


class Lead(BaseModel):
    """The record that flows through every stage. Stages fill in more fields as it advances."""

    # --- stage 1 (discovery) ---
    place_id: str
    name: str
    source: Source = "google_places"
    category: str | None = None
    place_type: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    has_website: bool = False
    is_operational: bool = True

    # --- stage 3 (enrichment) ---
    email: str | None = None
    owner_name: str | None = None
    site_text: str | None = None  # scraped, readable homepage/about text
    reviews: list[str] = Field(default_factory=list)
    detected_tech: list[str] = Field(default_factory=list)  # booking platforms, etc.

    # --- stage 4 (scoring) ---
    fit_score: int | None = None  # 0-100
    detected_signals: list[str] = Field(default_factory=list)
    disqualifiers_hit: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    suggested_opener: str | None = None

    # --- cross-run store (display only; not a Stage contract) ---
    lead_state: LeadState | None = None

    @property
    def contactable(self) -> bool:
        return bool(self.phone or self.email)


class ScoreResult(BaseModel):
    """Structured JSON contract returned by the Stage 4 LLM call (idea.md §7)."""

    fit_score: int = Field(ge=0, le=100)
    detected_signals: list[str] = Field(default_factory=list)
    disqualifiers_hit: list[str] = Field(default_factory=list)
    reasoning: str = ""
    suggested_opener: str = ""


class DropRecord(BaseModel):
    """An audit row for a lead dropped in Stage 2, with the reason."""

    place_id: str
    name: str
    reason: str
