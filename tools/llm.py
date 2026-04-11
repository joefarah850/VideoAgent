"""
Centralised LLM client – backed by litellm so the provider/model can be
switched at runtime without changing any other code.

Provider routing (litellm model string):
  Ollama     →  "ollama/llama3.1:8b"          (local, no key)
  OpenAI     →  "gpt-4o", "gpt-4o-mini", …    (needs OPENAI_API_KEY)
  Anthropic  →  "claude-opus-4-6", …           (needs ANTHROPIC_API_KEY)

Active config lives in LLM_CONFIG (a simple dict) which is mutated by the
/api/config endpoints at runtime, and persisted to .env on save.
"""
from __future__ import annotations

import json
import os
from typing import Any

import litellm
from litellm import completion as _completion

litellm.suppress_debug_info = True

# ── Runtime-mutable config ────────────────────────────────────────────────────
# Loaded once from env/defaults; mutated by /api/config save.

LLM_CONFIG: dict[str, Any] = {
    "provider":       os.getenv("LLM_PROVIDER", "ollama"),   # ollama | openai | anthropic
    "model":          os.getenv("LLM_MODEL",    "llama3.1:8b"),
    "openai_key":     os.getenv("OPENAI_API_KEY",     ""),
    "anthropic_key":  os.getenv("ANTHROPIC_API_KEY",  ""),
}

# ── Model catalogues shown in the UI ─────────────────────────────────────────

MODEL_CATALOGUE: dict[str, list[dict]] = {
    "ollama": [
        {"id": "llama3.1:8b",   "name": "Llama 3.1 8B",   "note": "Fast, good for most tasks"},
        {"id": "llama3.1:70b",  "name": "Llama 3.1 70B",  "note": "Slower, much smarter"},
        {"id": "llama3.3:70b",  "name": "Llama 3.3 70B",  "note": "Latest Meta model"},
        {"id": "mistral:7b",    "name": "Mistral 7B",      "note": "Great instruction following"},
        {"id": "qwen2.5:14b",   "name": "Qwen 2.5 14B",   "note": "Strong multilingual"},
        {"id": "deepseek-r1:8b","name": "DeepSeek R1 8B",  "note": "Reasoning model"},
    ],
    "openai": [
        {"id": "gpt-4o",        "name": "GPT-4o",          "note": "Best OpenAI model"},
        {"id": "gpt-4o-mini",   "name": "GPT-4o Mini",     "note": "Fast & cheap"},
        {"id": "gpt-4-turbo",   "name": "GPT-4 Turbo",     "note": "Previous generation"},
    ],
    "anthropic": [
        {"id": "claude-opus-4-6",   "name": "Claude Opus 4.6",   "note": "Most powerful"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "note": "Best balance"},
        {"id": "claude-haiku-4-5",  "name": "Claude Haiku 4.5",  "note": "Fastest & cheapest"},
    ],
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _litellm_model() -> str:
    """Build the litellm model string from current config."""
    provider = LLM_CONFIG["provider"]
    model    = LLM_CONFIG["model"]
    if provider == "ollama":
        return f"ollama/{model}"
    # openai and anthropic use the model ID directly
    return model


def _extra_kwargs() -> dict:
    """API key kwargs for litellm."""
    provider = LLM_CONFIG["provider"]
    if provider == "openai" and LLM_CONFIG["openai_key"]:
        return {"api_key": LLM_CONFIG["openai_key"]}
    if provider == "anthropic" and LLM_CONFIG["anthropic_key"]:
        return {"api_key": LLM_CONFIG["anthropic_key"]}
    return {}


# ── Public API ────────────────────────────────────────────────────────────────

def chat(
    messages: list[dict],
    *,
    json_mode: bool = False,
    model: str | None = None,
) -> str:
    """
    Single-turn completion. Returns the assistant text.
    json_mode=True requests JSON output and strips any markdown fences.
    """
    kwargs: dict[str, Any] = {
        "model":    model or _litellm_model(),
        "messages": messages,
        **_extra_kwargs(),
    }
    if json_mode:
        try:
            kwargs["response_format"] = {"type": "json_object"}
        except Exception:
            pass  # some models ignore this; we strip fences anyway

    resp = _completion(**kwargs)
    text = resp.choices[0].message.content or ""

    if json_mode:
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    return text


def chat_json(messages: list[dict], model: str | None = None) -> Any:
    """chat() but parses and returns the JSON value."""
    return json.loads(chat(messages, json_mode=True, model=model))


def stream_completion(messages: list[dict], tools: list | None = None) -> Any:
    """
    Streaming completion used by the agent loop.
    Returns a litellm streaming iterator (same interface as openai).
    """
    kwargs: dict[str, Any] = {
        "model":    _litellm_model(),
        "messages": messages,
        "stream":   True,
        **_extra_kwargs(),
    }
    if tools:
        kwargs["tools"] = tools
    return _completion(**kwargs)
