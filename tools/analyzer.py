"""
Video analyzer – transcribes audio and identifies viral-worthy moments.

Transcription priority:
  1. AssemblyAI (fast, cloud, if API key set)
  2. OpenAI Whisper (local, slower but free)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from config import ASSEMBLYAI_API_KEY
from tools.llm import chat_json


def transcribe_video(video_path: str) -> dict[str, Any]:
    """
    Transcribe a video file.  Returns:
      {
        "transcript": str,                   # full text
        "segments": [{"start": float, "end": float, "text": str}, ...]
      }
    """
    video_path = str(Path(video_path).resolve())

    if ASSEMBLYAI_API_KEY:
        return _transcribe_assemblyai(video_path)
    return _transcribe_whisper(video_path)


def _transcribe_assemblyai(video_path: str) -> dict[str, Any]:
    import assemblyai as aai

    aai.settings.api_key = ASSEMBLYAI_API_KEY
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(video_path)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {transcript.error}")

    segments = [
        {"start": u.start / 1000.0, "end": u.end / 1000.0, "text": u.text}
        for u in (transcript.utterances or [])
    ]
    return {"transcript": transcript.text or "", "segments": segments}


def _transcribe_whisper(video_path: str) -> dict[str, Any]:
    import whisper  # openai-whisper

    model = whisper.load_model("base")
    result = model.transcribe(video_path, word_timestamps=True)

    segments = [
        {"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
        for seg in result.get("segments", [])
    ]
    return {"transcript": result.get("text", ""), "segments": segments}


def find_viral_moments(
    transcript_data: dict[str, Any],
    num_clips: int = 5,
    style: str = "dramatic and epic",
) -> list[dict[str, Any]]:
    """
    Use Claude to identify the most viral-worthy moments in a transcript.

    Returns a list of dicts:
      [{"start": float, "end": float, "hook": str, "why_viral": str, "suggested_title": str}, ...]
    """
    transcript_text = transcript_data.get("transcript", "")
    segments_json   = json.dumps(transcript_data.get("segments", []), indent=2)

    prompt = f"""You are a viral short-form video expert. Analyze this transcript and identify the {num_clips} most viral-worthy moments.

TARGET STYLE: {style}

For each clip, identify a 15-60 second window that:
- Opens with a strong hook (first 3 seconds must grab attention)
- Contains a surprising insight, emotional peak, or compelling story beat
- Ends on a satisfying note or a cliffhanger
- Would perform well on Instagram Reels / TikTok

TRANSCRIPT (full):
{transcript_text}

TIMED SEGMENTS:
{segments_json}

Return ONLY a JSON array (no extra text):
[
  {{
    "start": <float seconds>,
    "end": <float seconds>,
    "hook": "<first sentence that grabs attention>",
    "why_viral": "<one sentence explanation>",
    "suggested_title": "<punchy title for the clip>",
    "suggested_caption": "<suggested IG caption with hashtags>"
  }}
]"""

    return chat_json([{"role": "user", "content": prompt}])
