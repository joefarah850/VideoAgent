"""
Voice cloning and voiceover generation via Voicebox (https://voicebox.sh).

Voicebox is a free, open-source, local-first voice studio.
It runs a FastAPI server on localhost:17493.

Setup:
  git clone https://github.com/jamiepine/voicebox
  cd voicebox && just setup && just dev
  Then enable the local API in Voicebox Settings.

API endpoints used:
  POST /generate            – synthesise speech
  GET  /profiles            – list cloned voice profiles
  POST /profiles            – create a new voice profile
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

import requests

from config import OUTPUT_DIR, TEMP_DIR
from tools.llm import chat

VOICEBOX_BASE = "http://localhost:17493"


# ── Connection check ──────────────────────────────────────────────────────────

def _voicebox_available() -> bool:
    try:
        r = requests.get(f"{VOICEBOX_BASE}/profiles", timeout=3)
        return r.status_code < 500
    except Exception:
        return False


# ── Voice profile management ──────────────────────────────────────────────────

def list_voices() -> list[dict[str, Any]]:
    """List all available cloned voice profiles in Voicebox."""
    if not _voicebox_available():
        raise RuntimeError("Voicebox is not running. Start it with: cd voicebox && just dev")
    resp = requests.get(f"{VOICEBOX_BASE}/profiles", timeout=10)
    resp.raise_for_status()
    return resp.json()


def clone_voice(
    audio_samples: list[str],
    voice_name: str = "MyVoice",
    description: str = "My cloned voice for video narration",
) -> str:
    """
    Upload audio samples to Voicebox and create a cloned voice profile.

    audio_samples: list of local file paths (wav/mp3, ~3 seconds minimum each)
    Returns: profile_id to use in generate_voiceover()
    """
    if not _voicebox_available():
        raise RuntimeError("Voicebox is not running. Start it with: cd voicebox && just dev")

    files = []
    handles = []
    for path in audio_samples:
        p   = Path(path)
        fh  = open(p, "rb")
        handles.append(fh)
        files.append(("files", (p.name, fh, "audio/mpeg")))

    try:
        resp = requests.post(
            f"{VOICEBOX_BASE}/profiles",
            data={"name": voice_name, "description": description},
            files=files,
            timeout=60,
        )
        resp.raise_for_status()
    finally:
        for fh in handles:
            fh.close()

    profile = resp.json()
    profile_id = profile.get("id") or profile.get("profile_id")
    print(f"✅  Voice cloned! profile_id = {profile_id}")
    print(f"    Save this as VOICEBOX_PROFILE_ID in your .env")
    return str(profile_id)


# ── TTS synthesis ─────────────────────────────────────────────────────────────

def generate_voiceover(
    script: str,
    profile_id: str | None = None,
    language: str = "en",
    output_name: str | None = None,
) -> str:
    """
    Synthesise a voiceover for the given script using a Voicebox cloned voice.
    Returns: path to the generated audio file (wav/mp3).
    """
    if not _voicebox_available():
        raise RuntimeError("Voicebox is not running. Start it with: cd voicebox && just dev")

    # Use env default if no profile_id passed
    if not profile_id:
        import os
        profile_id = os.getenv("VOICEBOX_PROFILE_ID", "")

    out_name = output_name or f"voiceover_{abs(hash(script[:40]))}.wav"
    out_path = str(TEMP_DIR / out_name)

    payload: dict[str, Any] = {
        "text":     script,
        "language": language,
    }
    if profile_id:
        payload["profile_id"] = profile_id

    resp = requests.post(
        f"{VOICEBOX_BASE}/generate",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()

    # Response is binary audio
    with open(out_path, "wb") as f:
        f.write(resp.content)

    return out_path


# ── Apply voiceover to video ──────────────────────────────────────────────────

def apply_voiceover(
    video_path: str,
    voiceover_path: str,
    original_audio_volume: float = 0.20,
    output_name: str | None = None,
) -> str:
    """
    Merge a voiceover audio file onto a video using ffmpeg.
    original_audio_volume: 0.0 = fully replace, 0.2 = keep original quietly.
    Returns path to the output video.
    """
    import subprocess
    video_path     = str(Path(video_path).resolve())
    voiceover_path = str(Path(voiceover_path).resolve())
    out_name       = output_name or f"vo_{Path(video_path).stem}.mp4"
    out_path       = str(OUTPUT_DIR / out_name)

    if original_audio_volume > 0:
        filter_complex = (
            f"[0:a]volume={original_audio_volume}[orig];"
            f"[1:a]volume=1.0[vo];"
            f"[orig][vo]amix=inputs=2:duration=first[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voiceover_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            out_path,
        ]
    else:
        # Fully replace audio
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voiceover_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest",
            out_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-600:]}")

    return out_path


# ── Narration script writing ──────────────────────────────────────────────────

def generate_viral_narration(
    topic: str,
    style: str = "dramatic and inspirational",
) -> str:
    """
    Use the local LLM to write a compelling 30-60 second narration script
    optimised for viral short-form video. Returns the script text.
    """
    return chat([{"role": "user", "content": f"""Write a compelling 30-60 second narration script for a viral short-form video about:

TOPIC: {topic}
STYLE: {style}

Rules:
- Hook in the first 3 seconds (surprising stat, bold claim, or provocative question)
- Short punchy sentences - easy to say out loud with dramatic pauses
- Build to an emotional peak or revelation
- End with a powerful closing line or call to action
- NO filler words, NO jargon
- First or second person ("you" / "I")

Return ONLY the script text, no labels or stage directions."""}]).strip()
