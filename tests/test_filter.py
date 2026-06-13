from __future__ import annotations

from leadscout.stages.discover import discover
from leadscout.stages.filter import filter_leads


def test_filter_keeps_only_qualified(geo, niche, icp, fixture_clients):
    places, _, _ = fixture_clients
    raw = discover(geo, niche, places)
    kept, dropped = filter_leads(raw, icp, niche)

    kept_ids = {x.place_id for x in kept}
    dropped_ids = {d.place_id for d in dropped}

    # Survivors: operational, dentist, in size range, with a phone.
    assert kept_ids == {"p_bright", "p_cityhosp"}

    # Each reject is dropped for the right deterministic reason.
    reasons = {d.place_id: d.reason for d in dropped}
    assert "size_proxy" in reasons["p_tiny"]      # 2 reviews < min 5
    assert "size_proxy" in reasons["p_mega"]      # 500 reviews > max 150
    assert "website" in reasons["p_nosite"]       # require_website
    assert "operational" in reasons["p_closed"]   # permanently closed
    assert "allowlist" in reasons["p_pizza"]      # restaurant, not dentist
    assert "contactability" in reasons["p_nocontact"]  # no phone, no named email yet
    assert dropped_ids == {"p_tiny", "p_mega", "p_nosite", "p_closed", "p_pizza", "p_nocontact"}


def test_every_drop_has_a_reason(geo, niche, icp, fixture_clients):
    places, _, _ = fixture_clients
    raw = discover(geo, niche, places)
    _, dropped = filter_leads(raw, icp, niche)
    assert all(d.reason for d in dropped)
