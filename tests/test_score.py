from __future__ import annotations

from leadscout.config import RunConfig
from leadscout.models import Lead
from leadscout.stages.score import DISQUALIFIED_SCORE_CAP, score


def _lead(pid: str, **kw) -> Lead:
    return Lead(place_id=pid, name=pid, place_type="dentist", **kw)


def test_opener_references_a_detected_signal(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True)
    out = score([_lead("p_bright")], icp, llm, cfg)
    lead = out[0]
    assert lead.detected_signals
    opener = lead.suggested_opener.lower()
    # Non-negotiable #6: opener must ground in a real detected signal.
    assert any(
        any(w in opener for w in sig.lower().replace("'", " ").split() if len(w) > 3)
        for sig in lead.detected_signals
    )


def test_disqualifier_caps_fit_score(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True)
    out = score([_lead("p_cityhosp")], icp, llm, cfg)
    lead = out[0]
    assert lead.disqualifiers_hit
    assert lead.fit_score <= DISQUALIFIED_SCORE_CAP


def test_budget_ceiling_stops_scoring(icp, fixture_clients):
    _, _, llm = fixture_clients
    # Budget below the per-call price => zero calls allowed.
    cfg = RunConfig(offline=True, budget_usd=0.0)
    out = score([_lead("p_bright"), _lead("p_cityhosp")], icp, llm, cfg)
    assert out == []
    assert llm.call_count == 0


def test_max_score_caps_calls(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True, max_score=1)
    score([_lead("p_bright"), _lead("p_cityhosp")], icp, llm, cfg)
    assert llm.call_count == 1


def test_results_ranked_desc(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True)
    out = score([_lead("p_cityhosp"), _lead("p_bright")], icp, llm, cfg)
    scores = [x.fit_score for x in out]
    assert scores == sorted(scores, reverse=True)
    assert out[0].place_id == "p_bright"
