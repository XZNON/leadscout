from __future__ import annotations

from leadscout.models import Lead
from leadscout.stages.enrich import _best_owner, _candidate_pages, enrich, enrich_lead


def _bright() -> Lead:
    return Lead(
        place_id="p_bright", name="Bright Smile Dental", place_type="dentist",
        website="https://brightsmile.example", phone="+91 80 1234 5678",
        review_count=42, has_website=True,
    )


def _family() -> Lead:
    return Lead(
        place_id="p_family", name="Family Dental Care", place_type="dentist",
        website="https://familydental.example", phone="+91 80 9876 5432",
        review_count=15, has_website=True,
    )


def _team() -> Lead:
    return Lead(
        place_id="p_team", name="Team Clinic", place_type="dentist",
        website="https://teamclinic.example", phone="+91 80 5555 1234",
        review_count=20, has_website=True,
    )


def _plain() -> Lead:
    return Lead(
        place_id="p_plain", name="Plain Clinic", place_type="dentist",
        website="https://plainclinic.example", phone="+91 80 1111 2222",
        review_count=5, has_website=True,
    )


# ---------------------------------------------------------------------------
# Regression tests (must stay green)
# ---------------------------------------------------------------------------

def test_enrich_extracts_email_owner_and_text(fixture_clients, cache):
    _, http, _ = fixture_clients
    out = enrich_lead(_bright(), http, cache)
    assert out.email == "anita@brightsmile.example"
    assert out.owner_name == "Anita Rao"
    assert "online booking" in (out.site_text or "").lower()


def test_enrich_detects_booking_tech(fixture_clients, cache):
    _, http, _ = fixture_clients
    city = Lead(place_id="p_cityhosp", name="City Hospital Dental Wing", place_type="dentist",
                website="https://cityhospital.example", phone="+91 80 2222 3333",
                review_count=80, has_website=True)
    out = enrich_lead(city, http, cache)
    assert "Practo" in out.detected_tech


def test_enrich_is_cached_no_refetch(fixture_clients, cache):
    _, http, _ = fixture_clients
    leads = [_bright()]
    enrich(leads, http, cache)
    first = http.fetch_count
    assert first == 1
    enrich(leads, http, cache)  # warm cache
    assert http.fetch_count == first, "second enrich must hit cache, not the network"


# ---------------------------------------------------------------------------
# Unit tests — pure functions, no I/O
# ---------------------------------------------------------------------------

def test_best_owner_label_form():
    assert _best_owner("Owner: Ramesh Gupta and his team...") == "Ramesh Gupta"
    assert _best_owner("Proprietor: Sunita Mehta, BDS") == "Sunita Mehta"
    assert _best_owner("Founded by Dr. Meera Iyer in 2010.") == "Meera Iyer"
    assert _best_owner("Managing Director: Anil Kumar heads the clinic.") == "Anil Kumar"


def test_best_owner_no_match_returns_none():
    assert _best_owner("We are a family dental clinic serving Bengaluru.") is None
    assert _best_owner("Our dentists have 20 years of experience.") is None
    assert _best_owner("Contact us at info@clinic.example") is None
    assert _best_owner("") is None


def test_candidate_pages():
    pages = _candidate_pages("https://example.com")
    assert pages[0] == "https://example.com"
    assert "https://example.com/about" in pages
    assert "https://example.com/about-us" in pages
    assert "https://example.com/team" in pages
    assert "https://example.com/contact" in pages
    assert len(pages) == len(set(pages)), "pages must be deduped"


# ---------------------------------------------------------------------------
# Stage-level tests — fixture HTML
# ---------------------------------------------------------------------------

def test_enrich_extracts_owner_from_label(fixture_clients, cache):
    """Label-form owner on site ('Owner: Ramesh Gupta') is extracted without a Dr. prefix."""
    _, http, _ = fixture_clients
    out = enrich_lead(_family(), http, cache)
    assert out.owner_name == "Ramesh Gupta"


def test_enrich_multipage_owner(fixture_clients, cache):
    """Owner name only in the team section triggers an extra page fetch and is still found."""
    _, http, _ = fixture_clients
    out = enrich_lead(_team(), http, cache)
    assert out.owner_name == "Priya Sharma"
    # Homepage fetch + at least one extra page fetch to find the name.
    assert http.fetch_count >= 2, "multi-page path must perform extra fetch(es)"


def test_enrich_owner_absent_is_none(fixture_clients, cache):
    """Sites with no extractable owner return owner_name=None — never fabricated."""
    _, http, _ = fixture_clients
    out = enrich_lead(_plain(), http, cache)
    assert out.owner_name is None
