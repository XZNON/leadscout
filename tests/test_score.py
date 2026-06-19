from __future__ import annotations

import pytest
from pydantic import ValidationError

from leadscout.config import RunConfig
from leadscout.models import Lead
from leadscout.stages.score import DISQUALIFIED_SCORE_CAP, _overlaps, build_prompt, score


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


# --------------------------------------------------------- 07E: opener format variants


def _grounded(opener: str, signals: list[str]) -> bool:
    return any(_overlaps(opener, sig) for sig in signals)


def test_build_prompt_includes_only_requested_formats(icp):
    lead = _lead("p_bright", website="https://example.com")
    prompt_email = build_prompt(lead, icp, ["email"])
    assert "opener_email" in prompt_email
    assert "opener_call" not in prompt_email
    assert "opener_whatsapp" not in prompt_email

    prompt_call_wa = build_prompt(lead, icp, ["call", "whatsapp"])
    assert "opener_call" in prompt_call_wa
    assert "opener_whatsapp" in prompt_call_wa
    assert "opener_email" not in prompt_call_wa


def test_all_requested_variants_produced_and_grounded(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True, opener_formats=["call", "email", "whatsapp"])
    out = score([_lead("p_bright")], icp, llm, cfg)
    lead = out[0]
    sigs = lead.detected_signals
    assert lead.opener_call and _grounded(lead.opener_call, sigs)
    assert lead.opener_email and _grounded(lead.opener_email, sigs)
    assert lead.opener_whatsapp and _grounded(lead.opener_whatsapp, sigs)


def test_ungrounded_variant_is_rewritten(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True, opener_formats=["email"])
    out = score([_lead("p_ungrounded")], icp, llm, cfg)
    lead = out[0]
    generic = "Hi, hope you are well"
    assert generic not in lead.opener_email, "generic opener must be rewritten"
    assert _grounded(lead.opener_email, lead.detected_signals), "rewrite must cite a real signal"


def test_default_config_back_compat(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True)  # default: ["call"]
    out = score([_lead("p_bright")], icp, llm, cfg)
    lead = out[0]
    assert lead.suggested_opener == lead.opener_call
    assert lead.opener_email == ""
    assert lead.opener_whatsapp == ""
    assert _grounded(lead.suggested_opener, lead.detected_signals)


def test_primary_mirror_whatsapp(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True, opener_formats=["whatsapp"])
    out = score([_lead("p_bright")], icp, llm, cfg)
    lead = out[0]
    assert lead.suggested_opener == lead.opener_whatsapp


def test_multi_format_does_not_multiply_calls(icp, fixture_clients):
    _, _, llm = fixture_clients
    cfg = RunConfig(offline=True, budget_usd=0.0, opener_formats=["call", "email", "whatsapp"])
    out = score([_lead("p_bright"), _lead("p_cityhosp")], icp, llm, cfg)
    assert out == []
    assert llm.call_count == 0


def test_runconfig_from_env_parses_opener_formats(monkeypatch):
    monkeypatch.setenv("LEADSCOUT_OPENER_FORMATS", "email, whatsapp")
    cfg = RunConfig.from_env()
    assert cfg.opener_formats == ["email", "whatsapp"]


def test_runconfig_from_env_rejects_bad_format(monkeypatch):
    monkeypatch.setenv("LEADSCOUT_OPENER_FORMATS", "fax")
    with pytest.raises(ValidationError):
        RunConfig.from_env()
