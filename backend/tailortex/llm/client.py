"""One client for seven providers, using the user's own key.

- OpenAI, Google Gemini, Groq, Mistral, DeepSeek and OpenRouter all speak the
  OpenAI-compatible chat API, called over HTTPS with httpx in JSON mode.
- Anthropic goes through its official Python SDK with structured outputs.

Every reply is validated against a pydantic schema. A reply that doesn't
validate gets one repair attempt with the error. The key is used in memory for
the request only and is never logged or included in error messages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .providers import PROVIDERS, is_chat_model

T = TypeVar("T", bound=BaseModel)

TIMEOUT = httpx.Timeout(180.0, connect=15.0)
MAX_OUTPUT_TOKENS = 16000


class LLMError(Exception):
    """A provider error, safe to show to the user (never contains the key)."""

    def __init__(self, message: str, kind: str = "provider"):
        super().__init__(message)
        self.kind = kind  # auth | rate_limit | bad_request | refusal | network | invalid_output | provider


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls


@dataclass
class ModelInfo:
    id: str
    label: str
    price_in: float | None = None  # USD per million tokens, when the provider says
    price_out: float | None = None


@dataclass
class LLMClient:
    provider: str
    key: str
    model: str = ""
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise LLMError(f"Unknown provider '{self.provider}'.", "bad_request")
        self.info = PROVIDERS[self.provider]

    def __repr__(self) -> str:  # never show the key
        return f"LLMClient(provider={self.provider!r}, model={self.model!r})"

    # --- public -----------------------------------------------------------------

    async def complete(self, system: str, user: str, schema: type[T]) -> T:
        """Ask for a JSON object matching schema; validate it; repair once if needed."""
        if self.info.style == "anthropic":
            return await self._anthropic(system, user, schema)
        return await self._openai(system, user, schema)

    async def list_models(self) -> list[ModelInfo]:
        """The chat models this key can use, straight from the provider (also checks the key)."""
        if self.info.style == "anthropic":
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.key, max_retries=1, timeout=30.0)
            try:
                out = []
                async for m in client.models.list(limit=100):
                    out.append(ModelInfo(m.id, getattr(m, "display_name", None) or m.id))
                return out
            except anthropic.APIStatusError as e:
                raise _anthropic_error(e) from None
            except anthropic.APIConnectionError:
                raise LLMError("Couldn't reach Anthropic. Check your connection.", "network") from None
        async with httpx.AsyncClient(timeout=30.0) as http:
            try:
                r = await http.get(f"{self.info.base_url}/models", headers=self._headers())
            except httpx.HTTPError:
                raise LLMError(f"Couldn't reach {self.info.label}. Check your connection.", "network") from None
        if r.status_code != 200:
            raise _http_error(self.info.label, r)
        data = r.json().get("data", [])
        models = []
        for m in data:
            mid = str(m.get("id", "")).removeprefix("models/")
            if not mid or not is_chat_model(mid):
                continue
            label = m.get("name") or m.get("display_name") or mid
            pricing = m.get("pricing") or {}
            try:
                p_in = float(pricing["prompt"]) * 1e6 if "prompt" in pricing else None
                p_out = float(pricing["completion"]) * 1e6 if "completion" in pricing else None
            except (TypeError, ValueError):
                p_in = p_out = None
            models.append(ModelInfo(mid, str(label), p_in, p_out))
        models.sort(key=lambda x: x.id)
        return models

    # --- OpenAI-compatible --------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if self.provider == "openrouter":
            h["HTTP-Referer"] = "https://github.com/shreytiwari09/TailorTex"
            h["X-Title"] = "TailorTeX"
        return h

    async def _openai(self, system: str, user: str, schema: type[T]) -> T:
        system = system + "\n\n" + _json_instructions(schema)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text = await self._openai_call(messages, json_mode=True)
        try:
            return _parse(text, schema)
        except (ValueError, ValidationError) as e:
            messages += [
                {"role": "assistant", "content": text[:6000]},
                {"role": "user", "content": f"That reply wasn't valid: {_short(e)}. Reply again with only the corrected JSON object."},
            ]
            text = await self._openai_call(messages, json_mode=True)
            try:
                return _parse(text, schema)
            except (ValueError, ValidationError) as e2:
                raise LLMError(f"The model's reply didn't match the expected format ({_short(e2)}). Try another model.", "invalid_output") from None

    async def _openai_call(self, messages: list[dict], json_mode: bool) -> str:
        body: dict = {"model": self.model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            for attempt in range(3):
                try:
                    r = await http.post(f"{self.info.base_url}/chat/completions", headers=self._headers(), json=body)
                except httpx.TimeoutException:
                    raise LLMError(f"{self.info.label} took too long to answer. Try again or pick a faster model.", "network") from None
                except httpx.HTTPError:
                    raise LLMError(f"Couldn't reach {self.info.label}. Check your connection.", "network") from None
                if r.status_code == 400 and "response_format" in body and attempt == 0:
                    body.pop("response_format")  # some models don't support JSON mode; the prompt still asks for JSON
                    continue
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    import asyncio

                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                break
        if r.status_code != 200:
            raise _http_error(self.info.label, r)
        data = r.json()
        u = data.get("usage") or {}
        self.usage.add(Usage(int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0), 1))
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"{self.info.label} returned an empty reply.", "invalid_output") from None
        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if choice.get("finish_reason") == "length":
            raise LLMError("The model ran out of output tokens before finishing. Try a model with a larger output limit.", "invalid_output")
        return content

    # --- Anthropic ---------------------------------------------------------------

    async def _anthropic(self, system: str, user: str, schema: type[T]) -> T:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.key, max_retries=2, timeout=240.0)
        messages = [{"role": "user", "content": user}]
        try:
            try:
                resp = await client.messages.parse(
                    model=self.model, max_tokens=MAX_OUTPUT_TOKENS, system=system, messages=messages, output_format=schema,
                )
                self._anthropic_usage(resp)
                _check_stop(resp)
                if resp.parsed_output is not None:
                    return resp.parsed_output
                text = _anthropic_text(resp)
            except anthropic.BadRequestError as e:
                if "output_format" not in str(e) and "output_config" not in str(e) and "schema" not in str(e).lower():
                    raise
                # Older models without structured outputs: ask for JSON in the prompt instead.
                resp = await client.messages.create(
                    model=self.model, max_tokens=MAX_OUTPUT_TOKENS, system=system + "\n\n" + _json_instructions(schema), messages=messages,
                )
                self._anthropic_usage(resp)
                _check_stop(resp)
                text = _anthropic_text(resp)
            try:
                return _parse(text, schema)
            except (ValueError, ValidationError) as e:
                raise LLMError(f"The model's reply didn't match the expected format ({_short(e)}). Try another model.", "invalid_output") from None
        except anthropic.APIStatusError as e:
            raise _anthropic_error(e) from None
        except anthropic.APITimeoutError:
            raise LLMError("Anthropic took too long to answer. Try again.", "network") from None
        except anthropic.APIConnectionError:
            raise LLMError("Couldn't reach Anthropic. Check your connection.", "network") from None

    def _anthropic_usage(self, resp) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage.add(Usage(int(u.input_tokens or 0), int(u.output_tokens or 0), 1))


# --- helpers -----------------------------------------------------------------------


def _check_stop(resp) -> None:
    if resp.stop_reason == "refusal":
        raise LLMError("The model declined this request. Try again or pick another model.", "refusal")
    if resp.stop_reason == "max_tokens":
        raise LLMError("The model ran out of output tokens before finishing.", "invalid_output")


def _anthropic_text(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _anthropic_error(e) -> LLMError:
    status = getattr(e, "status_code", 0)
    if status in (401, 403):
        return LLMError("Anthropic rejected the key. Check that it's correct and active.", "auth")
    if status == 404:
        return LLMError("That Anthropic model isn't available to this key.", "bad_request")
    if status == 429:
        return LLMError("Anthropic rate limit reached. Wait a minute and try again.", "rate_limit")
    msg = getattr(e, "message", "") or str(e)
    return LLMError(f"Anthropic error ({status}): {_scrub(msg)[:300]}", "bad_request" if status and status < 500 else "provider")


def _http_error(label: str, r: httpx.Response) -> LLMError:
    try:
        payload = r.json()
        err = payload.get("error", payload) if isinstance(payload, dict) else payload
        if isinstance(err, list) and err:
            err = err[0].get("error", err[0]) if isinstance(err[0], dict) else err[0]
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
    except ValueError:
        msg = r.text
    msg = _scrub(str(msg))[:300]
    if r.status_code in (401, 403) or "api key" in msg.lower() and "invalid" in msg.lower():
        return LLMError(f"{label} rejected the key. Check that it's correct and active.", "auth")
    if r.status_code == 404:
        return LLMError(f"That {label} model isn't available to this key.", "bad_request")
    if r.status_code == 429:
        return LLMError(f"{label} rate limit or quota reached. Wait a minute, or use a different key.", "rate_limit")
    return LLMError(f"{label} error ({r.status_code}): {msg}", "bad_request" if r.status_code < 500 else "provider")


def _scrub(msg: str) -> str:
    """Remove anything that looks like a key from a provider's error message."""
    return re.sub(r"(sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{10,}|gsk_[A-Za-z0-9]{10,})", "[key]", msg)


def _json_instructions(schema: type[BaseModel]) -> str:
    return (
        "Reply with a single JSON object and nothing else (no prose, no code fences). "
        "It must match this JSON Schema:\n" + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


def _parse(text: str, schema: type[T]) -> T:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in the reply")
        t = t[start : end + 1]
    return schema.model_validate(json.loads(t))


def _short(e: Exception) -> str:
    s = str(e).replace("\n", " ")
    return s[:400]
