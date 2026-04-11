"""
Centralised LLM client – backed by litellm.

Two independent model slots:
  AGENT  – used by agent.py for orchestration / tool-calling
  TASKS  – used by tools (viral analysis, script writing, Blender code, etc.)

Each slot has its own provider + model + API key.
Both are configured via /api/config and persisted to .env.
"""
from __future__ import annotations

import json
import os
from typing import Any

import litellm
from litellm import completion as _completion

litellm.suppress_debug_info = True

# ── Runtime-mutable config ────────────────────────────────────────────────────

LLM_CONFIG: dict[str, Any] = {
    # Agent orchestration model (tool-calling, reasoning)
    "agent_provider":  os.getenv("AGENT_LLM_PROVIDER", "ollama"),
    "agent_model":     os.getenv("AGENT_LLM_MODEL",    "llama3.1:8b"),

    # Tasks model (script writing, viral analysis, Blender code, narration)
    "tasks_provider":  os.getenv("TASKS_LLM_PROVIDER", "ollama"),
    "tasks_model":     os.getenv("TASKS_LLM_MODEL",    "llama3.1:8b"),

    # API keys (shared across both slots)
    "openai_key":      os.getenv("OPENAI_API_KEY",     ""),
    "anthropic_key":   os.getenv("ANTHROPIC_API_KEY",  ""),

    # AI video generation keys
    "kling_key":       os.getenv("KLING_API_KEY",      ""),
    "luma_key":        os.getenv("LUMA_API_KEY",       ""),
    "runway_key":      os.getenv("RUNWAY_API_KEY",     ""),
    "replicate_key":   os.getenv("REPLICATE_API_KEY",  ""),
    "google_key":      os.getenv("GOOGLE_API_KEY",     ""),
}

# ── Model catalogues ──────────────────────────────────────────────────────────

MODEL_CATALOGUE: dict[str, list[dict]] = {
    "ollama": [
        {"id": "llama3.1:8b",    "name": "Llama 3.1 8B",    "note": "Fast, good for most tasks"},
        {"id": "llama3.1:70b",   "name": "Llama 3.1 70B",   "note": "Slower, much smarter"},
        {"id": "llama3.3:70b",   "name": "Llama 3.3 70B",   "note": "Latest Meta model"},
        {"id": "mistral:7b",     "name": "Mistral 7B",       "note": "Great instruction following"},
        {"id": "qwen2.5:14b",    "name": "Qwen 2.5 14B",    "note": "Strong multilingual"},
        {"id": "deepseek-r1:8b", "name": "DeepSeek R1 8B",  "note": "Reasoning model"},
    ],
    "openai": [
        {"id": "gpt-4o",         "name": "GPT-4o",           "note": "Best OpenAI model"},
        {"id": "gpt-4o-mini",    "name": "GPT-4o Mini",      "note": "Fast & cheap"},
        {"id": "gpt-4-turbo",    "name": "GPT-4 Turbo",      "note": "Previous generation"},
    ],
    "anthropic": [
        {"id": "claude-opus-4-6",    "name": "Claude Opus 4.6",    "note": "Most powerful"},
        {"id": "claude-sonnet-4-6",  "name": "Claude Sonnet 4.6",  "note": "Best balance"},
        {"id": "claude-haiku-4-5",   "name": "Claude Haiku 4.5",   "note": "Fastest & cheapest"},
    ],
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_model_str(provider: str, model: str) -> str:
    if provider == "ollama":
        return f"ollama/{model}"
    return model  # openai / anthropic use the model ID directly


def _api_key_kwargs(provider: str) -> dict:
    if provider == "openai" and LLM_CONFIG["openai_key"]:
        return {"api_key": LLM_CONFIG["openai_key"]}
    if provider == "anthropic" and LLM_CONFIG["anthropic_key"]:
        return {"api_key": LLM_CONFIG["anthropic_key"]}
    return {}


def _agent_model_str()  -> str: return _build_model_str(LLM_CONFIG["agent_provider"], LLM_CONFIG["agent_model"])
def _tasks_model_str()  -> str: return _build_model_str(LLM_CONFIG["tasks_provider"], LLM_CONFIG["tasks_model"])
def _agent_api_kwargs() -> dict: return _api_key_kwargs(LLM_CONFIG["agent_provider"])
def _tasks_api_kwargs() -> dict: return _api_key_kwargs(LLM_CONFIG["tasks_provider"])


# ── Public API ────────────────────────────────────────────────────────────────

def chat(
    messages: list[dict],
    *,
    json_mode: bool = False,
    model: str | None = None,
) -> str:
    """
    Single-turn completion using the TASKS model (or explicit model override).
    Used by all generation tools: viral analysis, scripts, Blender code, narration.
    """
    kwargs: dict[str, Any] = {
        "model":    model or _tasks_model_str(),
        "messages": messages,
        **_tasks_api_kwargs(),
    }
    if json_mode:
        try:
            kwargs["response_format"] = {"type": "json_object"}
        except Exception:
            pass

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
    Streaming completion using the AGENT model.
    Used exclusively by the agent orchestration loop in agent.py.
    """
    kwargs: dict[str, Any] = {
        "model":    _agent_model_str(),
        "messages": messages,
        "stream":   True,
        **_agent_api_kwargs(),
    }
    if tools:
        kwargs["tools"] = tools
    return _completion(**kwargs)
