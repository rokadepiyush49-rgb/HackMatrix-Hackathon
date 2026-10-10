"""The Claude integration, exercised against a fake client — no network, no cost.

What must hold whatever the model does: every answer passes the cite-or-drop verifier, and any
failure (refusal, truncation, API error, malformed JSON) falls back to the deterministic engine.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.copilot import engine

CTX = {
    "argument": {"claim": "Employee-enabled takeover", "rebuttals": [], "missing": [], "typology": "INSIDER_ATO"},
    "links": [{"code": "E5", "t": "2026-09-21T22:34:02+05:30", "title": "Payout", "detail": "₹4.90 L to A-7731",
               "evidence_codes": ["EV-101"]}],
    "dims": [{"label": "Transaction", "level": "HIGH", "summary": "3 new payees", "supporting": ["EV-101"],
              "contradicting": []}],
    "evidence": [{"code": "EV-101", "summary": "IMPS ₹4,90,000 from A-5520 to A-7731 at 22:34",
                  "source_system": "CBS", "reliability": "A", "credibility": 1, "facts": {}, "entities": ["A-5520", "A-7731"]}],
}


def _response(text: str, stop: str = "end_turn", model: str = "claude-opus-5-5"):
    usage = SimpleNamespace(input_tokens=900, output_tokens=60, cache_read_input_tokens=0, cache_creation_input_tokens=800)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop, model=model, usage=usage)


class FakeClient:
    def __init__(self, result):
        self.result, self.calls = result, []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture()
def llm(monkeypatch):
    """Turn the LLM path on with a fake client; returns a setter for the client's behaviour."""
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_enabled", True)
    monkeypatch.setattr(s, "anthropic_api_key", "test-key")

    def use(result, provider: str = "anthropic") -> FakeClient:
        monkeypatch.setattr(s, "llm_provider", provider)
        fake = FakeClient(result)
        monkeypatch.setattr(engine, "_client", lambda *_: fake)
        return fake

    return use


GOOD = json.dumps({"sentences": [
    {"text": "₹4.90 L left A-5520 for A-7731 at 22:34.", "evidence": ["EV-101"]},
    {"text": "The employee confessed.", "evidence": []},  # uncited → must be dropped
]})


def test_first_party_request_shape_and_verified_answer(llm):
    fake = llm(_response(GOOD))
    a = engine.ask(CTX, "What happened?")
    assert a.mode == "llm" and a.model == "claude-opus-5-5"
    assert [s.text for s in a.sentences] == ["₹4.90 L left A-5520 for A-7731 at 22:34."]
    assert a.dropped and a.dropped[0].reason == "no evidence cited"

    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["effort"] == "medium"
    evidence_block, question_block = kw["messages"][0]["content"]
    assert evidence_block["cache_control"] == {"type": "ephemeral"}, "case evidence is the cached prefix"
    assert "cache_control" not in question_block and "What happened?" in question_block["text"]


def test_bedrock_uses_iam_client_without_unsupported_features(llm):
    fake = llm(_response("```json\n" + GOOD + "\n```", model="anthropic.claude-opus-5-5"), provider="bedrock")
    a = engine.ask(CTX, "What happened?")
    assert a.mode == "llm" and len(a.sentences) == 1
    kw = fake.calls[0]
    assert kw["model"] == "anthropic.claude-opus-5-5"
    assert "fallbacks" not in kw and "betas" not in kw, "server-side fallback isn't offered on Bedrock"
    assert "format" not in kw["output_config"], "structured outputs aren't offered on Bedrock"
    assert "JSON object" in kw["system"]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_refusal_or_truncation_falls_back_to_deterministic(llm, stop):
    llm(_response(GOOD, stop=stop))
    a = engine.ask(CTX, "What happened?")
    assert a.mode == "deterministic" and a.sentences


def test_api_errors_fall_back_and_are_logged(llm, caplog):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    llm(anthropic.APIConnectionError(message="down", request=req))
    with caplog.at_level("WARNING", logger="sutra.copilot"):
        a = engine.ask(CTX, "What happened?")
    assert a.mode == "deterministic"
    assert "llm.unreachable" in caplog.text and "EV-101" not in caplog.text, "never log evidence content"


def test_malformed_json_falls_back(llm):
    llm(_response("Sure! Here's what happened…"))
    assert engine.ask(CTX, "What happened?").mode == "deterministic"


def test_disabled_llm_never_calls_the_client(llm, monkeypatch):
    from app.core.config import get_settings

    fake = llm(_response(GOOD))
    monkeypatch.setattr(get_settings(), "llm_enabled", False)
    assert engine.ask(CTX, "What happened?").mode == "deterministic"
    assert fake.calls == []
