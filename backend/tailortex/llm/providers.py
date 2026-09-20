"""The seven providers a user can bring a key from, and how to recognize each key."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    style: str  # "openai" (OpenAI-compatible chat API) or "anthropic" (official SDK)
    base_url: str
    key_url: str  # where to create a key
    free_tier: bool = False


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in [
        Provider("google", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai", "https://aistudio.google.com/app/apikey", True),
        Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "https://console.groq.com/keys", True),
        Provider("openai", "OpenAI", "openai", "https://api.openai.com/v1", "https://platform.openai.com/api-keys"),
        Provider("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com", "https://console.anthropic.com/settings/keys"),
        Provider("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", "https://openrouter.ai/keys", True),
        Provider("mistral", "Mistral", "openai", "https://api.mistral.ai/v1", "https://console.mistral.ai/api-keys", True),
        Provider("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1", "https://platform.deepseek.com/api_keys"),
    ]
}


def detect_provider(key: str) -> tuple[str | None, list[str]]:
    """(best guess, all plausible providers) from the key's shape."""
    k = key.strip()
    if k.startswith("sk-ant-"):
        return "anthropic", ["anthropic"]
    if k.startswith("sk-or-"):
        return "openrouter", ["openrouter"]
    if k.startswith("gsk_"):
        return "groq", ["groq"]
    if k.startswith("AIza"):
        return "google", ["google"]
    if k.startswith(("sk-proj-", "sk-svcacct-", "sk-admin-")):
        return "openai", ["openai"]
    if re.fullmatch(r"sk-[a-f0-9]{32}", k):
        return "deepseek", ["deepseek", "openai"]
    if k.startswith("sk-"):
        return "openai", ["openai", "deepseek"]
    if re.fullmatch(r"[A-Za-z0-9]{32}", k):
        return "mistral", ["mistral"]
    return None, list(PROVIDERS)


# Models that aren't for chat: embeddings, speech, images, moderation, and so on.
_NOT_CHAT = re.compile(
    r"embed|whisper|tts|dall-e|image|imagen|veo|audio|realtime|moderation|transcribe|davinci|babbage|"
    r"guard|aqa|computer-use|search-preview|native-audio|-live|learnlm|gemma-3n|robotics|orpheus|playai|"
    r"distil|ocr|codestral-embed|pixtral-large-2411",
    re.IGNORECASE,
)


def is_chat_model(model_id: str) -> bool:
    return not _NOT_CHAT.search(model_id)


def _version(model_id: str) -> tuple[float, ...]:
    return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", model_id)[:2]) or (0.0,)


def recommended_model(provider: str, ids: list[str]) -> str | None:
    """A sensible default from the provider's live model list (newest good-value model)."""
    if not ids:
        return None

    def newest(pattern: str) -> str | None:
        hits = [i for i in ids if re.search(pattern, i)]
        return max(hits, key=_version) if hits else None

    prefs: dict[str, list[str]] = {
        "google": [r"^gemini-[\d.]+-flash$", r"^gemini-[\d.]+-pro$", r"^gemini-[\d.]+-flash"],
        "openai": [r"^gpt-[\d.]+-mini$", r"^gpt-[\d.]+$", r"^gpt-4o-mini$"],
        "groq": [r"^openai/gpt-oss-120b$", r"^llama-3\.3-70b-versatile$", r"kimi-k2", r"70b"],
        "mistral": [r"^mistral-large-latest$", r"^mistral-medium-latest$", r"^mistral-small-latest$"],
        "deepseek": [r"^deepseek-chat$"],
        "openrouter": [r"^google/gemini-[\d.]+-flash$", r"^openai/gpt-[\d.]+-mini$", r"^deepseek/deepseek-chat"],
    }
    if provider == "anthropic":
        # The Models API lists newest first; prefer the newest top-tier model, then the mid tier.
        for family in ("opus", "sonnet"):
            hit = next((i for i in ids if family in i), None)
            if hit:
                return hit
        return ids[0]
    for pattern in prefs.get(provider, []):
        hit = newest(pattern)
        if hit:
            return hit
    return ids[0]


def fallback_models(provider: str, ids: list[str], current: str) -> list[str]:
    """Other models from the same provider to try when the chosen one stays overloaded, best first.

    Only stable names (no preview or experimental builds, which are the ones that run out of capacity), and only
    for Google Gemini, whose "high demand" errors are the common case.
    """
    if provider != "google":
        return []
    stable = [i for i in ids if re.fullmatch(r"gemini-[\d.]+-flash(-lite)?", i) and i != current]
    # a full Flash before a Flash-Lite, newer before older
    return sorted(stable, key=lambda i: (i.endswith("-lite"), tuple(-v for v in _version(i))))
