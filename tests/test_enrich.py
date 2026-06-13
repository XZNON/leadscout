from __future__ import annotations

from leadscout.models import Lead
from leadscout.stages.enrich import enrich, enrich_lead


def _bright() -> Lead:
    return Lead(
        place_id="p_bright", name="Bright Smile Dental", place_type="dentist",
        website="https://brightsmile.example", phone="+91 80 1234 5678",
        review_count=42, has_website=True,
    )


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
