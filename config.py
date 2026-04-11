"""
Configuration – loads from .env or environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# ── Ollama (local LLM – no API key required) ──────────────────────────────────
OLLAMA_BASE_URL  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ── Optional cloud API Keys ───────────────────────────────────────────────────
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
RUNWAYML_API_KEY    = os.getenv("RUNWAYML_API_KEY", "")
LUMAAI_API_KEY      = os.getenv("LUMAAI_API_KEY", "")
ASSEMBLYAI_API_KEY  = os.getenv("ASSEMBLYAI_API_KEY", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
TEMP_DIR   = Path(os.getenv("TEMP_DIR",   BASE_DIR / "temp"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ── Video defaults ────────────────────────────────────────────────────────────
CLIP_MIN_DURATION  = 15   # seconds
CLIP_MAX_DURATION  = 90   # seconds
CLIP_TARGET_FPS    = 30
CLIP_RESOLUTION    = (1080, 1920)  # portrait / Reels / TikTok

# ── Animation defaults ────────────────────────────────────────────────────────
ANIMATION_DURATION = 10   # seconds
ANIMATION_RATIO    = "1280:768"
