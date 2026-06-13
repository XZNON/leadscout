"""Offline tests for the live OpenAI scorer.

Every test injects a fake OpenAI client via the `client=` seam — zero network, zero key. The
fake mimics the SDK shape consumed by `LiveLlmClient.score`: resp.choices[0].message.parsed
(a ScoreResult) / .refusal, and resp.usage.prompt_tokens / .completion_tokens.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from leadscout.clients import LiveLlmClient, _cost_usd
from leadscout.config import RunConfig
from leadscout.models import ICPSpec, Lead, ScoreResult
from leadscout.stages.score import score


def _resp(parsed: ScoreResult | None, refusal: str | None, in_tok: int, out_tok: int):
    """Build a fake response object mirroring the SDK shape."""
    msg = SimpleNamespace(parsed=parsed, refusal=refusal)
    choice = SimpleNamespace(message=msg)
    usage = SimpleNamespace(prompt_tokens=in_tok, completion_tokens=out_tok)
    return SimpleNamespace(choices=[choice], usage=usage)


class _FakeParse:
    """Fake `client.beta.chat.completions.parse`: records call kwargs, returns queued responses.

    Each queued entry is either a response object (returned) or an Exception (raised), so tests
    can drive success, refusal, and transient-error paths.
    """

    def __init__(self, queue: list) -> None:
        self._queue = list(queue)
        self.calls: list[dict] = []

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def as_client(self) -> SimpleNamespace:
        completions = SimpleNamespace(parse=self._parse)
        chat = SimpleNamespace(completions=completions)
        return SimpleNamespace(beta=SimpleNamespace(chat=chat))


def _ok(fit: int = 70) -> ScoreResult:
    return ScoreResult(
        fit_score=fit,
        detected_signals=["no online booking"],
        disqualifiers_hit=[],
        reasoning="ok",
        suggested_opener="Noticed no online booking — wanted to reach out.",
    )


def _client(queue: list) -> tuple[LiveLlmClient, _FakeParse]:
    fake = _FakeParse(queue)
    return LiveLlmClient(api_key="test", client=fake.as_client()), fake


def test_score_parses_and_accrues_cost():
    expected = _ok()
    llm, _ = _client([_resp(expected, None, 1000, 500)])
    out = llm.score("gpt-4o-mini", "prompt")
    assert out == expected
    assert llm.call_count == 1
    assert llm.spent_usd == pytest.approx(1000 / 1000 * 0.00015 + 500 / 1000 * 0.00060)


def test_passes_model_and_response_format():
    llm, fake = _client([_resp(_ok(), None, 10, 10)])
    llm.score("gpt-4o-mini", "the prompt body")
    call = fake.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["response_format"] is ScoreResult
    assert call["messages"] == [{"role": "user", "content": "the prompt body"}]


def test_refusal_retries_then_raises():
    llm, fake = _client([
        _resp(None, "cannot help", 10, 10),
        _resp(None, "cannot help", 10, 10),
    ])
    with pytest.raises(ValueError):
        llm.score("gpt-4o-mini", "prompt")
    assert llm.call_count == 0
    assert llm.spent_usd == 0.0
    assert len(fake.calls) == 2  # one retry attempted


def test_refusal_then_success_recovers():
    expected = _ok()
    llm, _ = _client([
        _resp(None, "cannot help", 10, 10),
        _resp(expected, None, 100, 100),
    ])
    out = llm.score("gpt-4o-mini", "prompt")
    assert out == expected
    assert llm.call_count == 1


def test_parse_exception_retries_once():
    expected = _ok()
    llm, _ = _client([RuntimeError("boom"), _resp(expected, None, 10, 10)])
    assert llm.score("gpt-4o-mini", "prompt") == expected
    assert llm.call_count == 1


def test_parse_exception_twice_propagates():
    llm, _ = _client([RuntimeError("boom"), RuntimeError("boom again")])
    with pytest.raises(RuntimeError):
        llm.score("gpt-4o-mini", "prompt")
    assert llm.call_count == 0


def test_cost_usd_table_and_fallback(caplog):
    assert _cost_usd("gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
    with caplog.at_level(logging.WARNING):
        cost = _cost_usd("unknown-model", 1000, 1000)
    assert cost == pytest.approx(1000 / 1000 * 0.00015 + 1000 / 1000 * 0.00060)
    assert any("unknown-model" in r.message for r in caplog.records)


def _lead(pid: str) -> Lead:
    return Lead(place_id=pid, name=pid, place_type="dentist")


def test_live_client_obeys_budget_in_score_loop():
    icp = ICPSpec(product="p", buyer="b", pain_signals=["no online booking"])
    # Each response costs $1.20 (8M input tokens * $0.00015/1K), so two calls cross a $1.5 ceiling.
    def big():
        return _resp(_ok(), None, 8_000_000, 0)

    llm, _ = _client([big(), big(), big()])
    out = score([_lead("a"), _lead("b"), _lead("c")], icp, llm, RunConfig(budget_usd=1.5))
    # First call ($1.20) is allowed; before the second, spent ($1.20) < 1.5 so it also runs
    # ($2.40); the third sees spent >= budget and stops. Fewer than 3 calls proves the ceiling.
    assert llm.call_count < 3
    assert len(out) < 3
