"""A busy or rate-limited provider is waited out, a persistently overloaded Gemini model is swapped for a sibling,
and the person is told. No network: the provider is scripted."""

import asyncio

import httpx
import pytest
from pydantic import BaseModel

from tailortex.llm import client as llm_client
from tailortex.llm.client import LLMClient, LLMError
from tailortex.llm.providers import fallback_models


class Answer(BaseModel):
    ok: bool


BUSY = {"error": {"code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}}
GOOD = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
MODELS = {"data": [{"id": f"models/{m}"} for m in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-3-flash-preview", "gemini-2.5-pro", "text-embedding-004")]}


class Script:
    """Answers chat requests per model from a list of (status, json, headers) and records what happened."""

    def __init__(self, monkeypatch, per_model: dict[str, list]):
        self.per_model, self.sent, self.sleeps = per_model, [], []

        async def post(_self, url, **kw):
            model = kw["json"]["model"]
            self.sent.append(model)
            status, payload, *rest = self.per_model[model].pop(0)
            return httpx.Response(status, json=payload, headers=rest[0] if rest else {}, request=httpx.Request("POST", url))

        async def get(_self, url, **kw):
            return httpx.Response(200, json=MODELS, request=httpx.Request("GET", url))

        async def sleep(seconds):
            self.sleeps.append(seconds)

        monkeypatch.setattr(httpx.AsyncClient, "post", post)
        monkeypatch.setattr(httpx.AsyncClient, "get", get)
        monkeypatch.setattr(llm_client.asyncio, "sleep", sleep)


def make(notes: list[str], model="gemini-2.5-flash") -> LLMClient:
    async def notify(message: str):
        notes.append(message)

    return LLMClient(provider="google", key="AIzaTestKeyNotReal1234", model=model, notify=notify)


def test_a_busy_server_is_waited_out_and_the_person_is_told(monkeypatch):
    script = Script(monkeypatch, {"gemini-2.5-flash": [(503, BUSY), (503, BUSY, {"retry-after": "7"}), (200, GOOD)]})
    notes: list[str] = []
    out = asyncio.run(make(notes).complete("sys", "user", Answer))
    assert out.ok and script.sent == ["gemini-2.5-flash"] * 3
    assert len(notes) == 2 and "busy" in notes[0] and "try 2 of 5" in notes[0]
    assert 4 <= script.sleeps[0] <= 5 and 7 <= script.sleeps[1] <= 8  # the backoff, then the provider's Retry-After


def test_an_overloaded_model_is_swapped_for_a_sibling_and_it_is_recorded(monkeypatch):
    script = Script(monkeypatch, {"gemini-2.5-flash": [(503, BUSY)] * 5, "gemini-2.0-flash": [(200, GOOD)]})
    notes: list[str] = []
    llm = make(notes)
    assert asyncio.run(llm.complete("sys", "user", Answer)).ok
    assert script.sent.count("gemini-2.5-flash") == 5 and script.sent[-1] == "gemini-2.0-flash"
    assert llm.model == "gemini-2.0-flash" and llm.switched_from == "gemini-2.5-flash"
    assert any("Switching to gemini-2.0-flash" in n for n in notes)


def test_when_everything_stays_busy_the_error_says_what_to_do(monkeypatch):
    script = Script(monkeypatch, {m: [(503, BUSY)] * 5 for m in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash")})
    llm = make([])
    with pytest.raises(LLMError) as e:
        asyncio.run(llm.complete("sys", "user", Answer))
    assert e.value.kind == "overloaded" and "overloaded right now" in str(e.value) and "another model" in str(e.value)
    assert "AIza" not in str(e.value) and llm.model == "gemini-2.5-flash" and llm.switched_from is None
    assert set(script.sent) == {"gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"}  # tried the stable siblings, not the preview


def test_rate_limits_get_two_extra_tries_and_bad_keys_none(monkeypatch):
    script = Script(monkeypatch, {"gemini-2.5-flash": [(429, {"error": {"message": "quota"}})] * 3})
    with pytest.raises(LLMError) as e:
        asyncio.run(make([]).complete("sys", "user", Answer))
    assert e.value.kind == "rate_limit" and len(script.sent) == 3

    script = Script(monkeypatch, {"gemini-2.5-flash": [(401, {"error": {"message": "API key not valid"}})]})
    with pytest.raises(LLMError) as e:
        asyncio.run(make([]).complete("sys", "user", Answer))
    assert e.value.kind == "auth" and len(script.sent) == 1 and script.sleeps == []


def test_a_real_error_on_a_sibling_is_reported_not_hidden(monkeypatch):
    script = Script(monkeypatch, {"gemini-2.5-flash": [(503, BUSY)] * 5, "gemini-2.0-flash": [(400, {"error": {"message": "bad request"}})] * 2})
    with pytest.raises(LLMError) as e:
        asyncio.run(make([]).complete("sys", "user", Answer))
    assert e.value.kind == "bad_request" and script.sent[-1] == "gemini-2.0-flash"
    assert script.sent.count("gemini-2.0-flash") == 2  # the first 400 is retried once without JSON mode, in case that was the cause


def test_fallback_models_are_stable_siblings_only():
    ids = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash-image"]
    assert fallback_models("google", ids, "gemini-2.5-flash") == ["gemini-2.0-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"]
    assert fallback_models("openai", ["gpt-5-mini"], "gpt-5") == []


# --- quotas: Google counts per project per model, per day -------------------------------------------

# Gemini's own reply, as it arrives (list-wrapped, details in the body, no Retry-After header).
DAILY = [{"error": {
    "code": 429, "status": "RESOURCE_EXHAUSTED",
    "message": ("You exceeded your current quota, please check your plan and billing details.\n"
                "* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                "limit: 20, model: gemini-2.5-flash\nPlease retry in 38.63183958s."),
    "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
             "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
             "quotaDimensions": {"location": "global", "model": "gemini-2.5-flash"}, "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "38s"},
    ]}}]
PER_MINUTE = [{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for quota metric: requests per minute",
                         "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "11s"}]}}]


def test_a_used_up_daily_allowance_moves_to_another_model_instead_of_waiting(monkeypatch):
    script = Script(monkeypatch, {"gemini-2.5-flash": [(429, DAILY)], "gemini-2.0-flash": [(200, GOOD)]})
    notes: list[str] = []
    llm = make(notes)
    assert asyncio.run(llm.complete("sys", "user", Answer)).ok
    assert script.sleeps == []  # tomorrow's quota can't be waited for inside a run
    assert script.sent == ["gemini-2.5-flash", "gemini-2.0-flash"] and llm.model == "gemini-2.0-flash"
    assert any("out of its free allowance for today" in n for n in notes)


def test_when_every_model_is_out_the_error_says_a_new_key_would_not_help(monkeypatch):
    Script(monkeypatch, {m: [(429, DAILY)] * 2 for m in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash")})
    with pytest.raises(LLMError) as e:
        asyncio.run(make([]).complete("sys", "user", Answer))
    msg = str(e.value)
    assert e.value.kind == "rate_limit"
    assert "20 requests a day" in msg and "gemini-2.5-flash" in msg
    assert "new key won't help" in msg and "different model" in msg


def test_a_per_minute_limit_is_waited_out_for_as_long_as_google_asks(monkeypatch):
    script = Script(monkeypatch, {"gemini-2.5-flash": [(429, PER_MINUTE), (200, GOOD)]})
    notes: list[str] = []
    assert asyncio.run(make(notes).complete("sys", "user", Answer)).ok
    assert 11 <= script.sleeps[0] <= 12 and script.sent == ["gemini-2.5-flash"] * 2  # the body's retryDelay, not the backoff
    assert "rate limiting" in notes[0]


def test_a_per_minute_limit_that_does_not_clear_says_how_long_to_wait(monkeypatch):
    Script(monkeypatch, {"gemini-2.5-flash": [(429, PER_MINUTE)] * 3})
    with pytest.raises(LLMError) as e:
        asyncio.run(make([]).complete("sys", "user", Answer))
    assert "about 11 seconds" in str(e.value) and "daily" not in str(e.value)
