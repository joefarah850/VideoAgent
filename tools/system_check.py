"""
Runtime capability detection.

Checks which local tools are installed and which API keys are set,
so the agent and UI know exactly what's available before attempting anything.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def get_capabilities() -> dict[str, Any]:
    """
    Returns a dict of every capability the agent can use.
    Cached after first call (restart server to refresh).
    """
    caps: dict[str, Any] = {}

    # ── Local tools ──────────────────────────────────────────────────────────
    caps["ffmpeg"]   = _check_binary("ffmpeg",   ["ffmpeg", "-version"])
    caps["blender"]  = _check_blender()
    caps["voicebox"] = _check_voicebox()
    caps["ollama"]   = _check_ollama()

    # ── Optional API keys ────────────────────────────────────────────────────
    caps["elevenlabs"]   = bool(os.getenv("ELEVENLABS_API_KEY"))
    caps["runway"]       = bool(os.getenv("RUNWAYML_API_KEY"))
    caps["luma"]         = bool(os.getenv("LUMAAI_API_KEY"))
    caps["assemblyai"]   = bool(os.getenv("ASSEMBLYAI_API_KEY"))

    # ── Python packages ───────────────────────────────────────────────────────
    caps["whisper"]      = _check_import("whisper")

    # ── Derived feature flags (what the UI should enable/disable) ─────────────
    caps["features"] = {
        "chat":            caps["ollama"],
        "transcribe":      caps["ffmpeg"] and (caps["whisper"] or caps["assemblyai"]),
        "viral_clips":     caps["ffmpeg"] and caps["ollama"],
        "captions":        caps["ffmpeg"],
        "animation_3d":    caps["blender"] is not None,
        "animation_cloud": caps["runway"] or caps["luma"],
        "voiceover":       caps["voicebox"] or caps["elevenlabs"],
        "voice_clone":     caps["voicebox"],
        "full_pipeline":   caps["ffmpeg"] and caps["ollama"],
    }

    return caps


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_binary(name: str, cmd: list[str]) -> bool:
    if not shutil.which(name):
        return False
    try:
        subprocess.run(cmd, capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _check_blender() -> str | None:
    """Returns the Blender path if found, else None. Handles versioned Windows dirs."""
    import glob as _glob
    candidates = [
        shutil.which("blender"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/snap/bin/blender",
    ]
    # Windows: versioned dirs e.g. "Blender 4.2"
    for pattern in [
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        r"C:\Program Files (x86)\Blender Foundation\Blender*\blender.exe",
    ]:
        candidates.extend(sorted(_glob.glob(pattern), reverse=True))

    for c in candidates:
        if c and os.path.isfile(c):
            try:
                r = subprocess.run([c, "--version"], capture_output=True, timeout=8)
                if r.returncode == 0:
                    return c
            except Exception:
                pass
    return None


def _check_voicebox() -> bool:
    """Ping the Voicebox local API."""
    try:
        import requests
        r = requests.get("http://localhost:17493/profiles", timeout=2)
        return r.status_code < 500
    except Exception:
        return False


def _check_ollama() -> bool:
    """Ping Ollama and verify the configured model is pulled."""
    try:
        import requests
        from config import OLLAMA_MODEL
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code != 200:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        # Accept exact match or base name match (e.g. "llama3.1:8b" == "llama3.1:8b")
        base = OLLAMA_MODEL.split(":")[0]
        return any(base in m for m in models)
    except Exception:
        return False


def _check_import(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def describe_capabilities() -> str:
    """Human-readable summary for the UI or CLI."""
    caps = get_capabilities()
    lines = ["🔍  System capability check\n"]

    tool_checks = [
        ("ollama",   caps["ollama"],              "Ollama LLM (required)"),
        ("ffmpeg",   caps["ffmpeg"],              "Video processing"),
        ("blender",  caps["blender"] is not None, "3D animation rendering"),
        ("voicebox", caps["voicebox"],             "Local voice cloning (Voicebox)"),
        ("whisper",  caps["whisper"],              "Local transcription (Whisper)"),
    ]
    api_checks = [
        ("runway",     caps["runway"],     "Runway ML animation"),
        ("luma",       caps["luma"],       "Luma AI animation"),
        ("assemblyai", caps["assemblyai"], "AssemblyAI transcription"),
        ("elevenlabs", caps["elevenlabs"], "ElevenLabs TTS"),
    ]

    lines.append("Local tools:")
    for key, ok, label in tool_checks:
        lines.append(f"  {'✅' if ok else '❌'}  {label}")

    lines.append("\nAPI keys:")
    for key, ok, label in api_checks:
        lines.append(f"  {'✅' if ok else '⚠️ '}  {label}")

    lines.append("\nEnabled features:")
    for feat, ok in caps["features"].items():
        lines.append(f"  {'✅' if ok else '🔒'}  {feat.replace('_', ' ').title()}")

    return "\n".join(lines)
