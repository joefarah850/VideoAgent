"""
AI Video Generation – unified tool for cloud providers.

Supported providers (set via API key in config):
  kling      – Kling 3.0 (Kuaishou)
  luma       – Luma Dream Machine
  runway     – Runway Gen-4 Turbo
  sora       – OpenAI Sora 2 (uses openai_key)
  replicate  – Wan 2.5 via Replicate
  veo        – Google Veo 3.1 (via Gemini API)
"""
from __future__ import annotations

import os
import time
import urllib.request
import uuid
from pathlib import Path

from config import OUTPUT_DIR
from tools.llm import LLM_CONFIG

# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_video_from_url(url: str, output_name: str | None) -> str:
    """Download a video URL to OUTPUT_DIR and return the local path."""
    fname  = output_name or f"ai_video_{uuid.uuid4().hex[:8]}.mp4"
    if not fname.endswith((".mp4", ".mov", ".webm")):
        fname += ".mp4"
    dest = OUTPUT_DIR / fname
    urllib.request.urlretrieve(url, str(dest))
    return str(dest)


def _http_json(url: str, *, method: str = "GET", data: bytes | None = None,
               headers: dict | None = None) -> dict:
    """Minimal JSON HTTP call without requests dependency."""
    import json
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _poll(check_fn, *, interval: float = 5.0, timeout: float = 600.0) -> str:
    """
    Poll check_fn() every `interval` seconds until it returns a non-None string
    (the download URL), or until `timeout` seconds elapse.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check_fn()
        if result:
            return result
        time.sleep(interval)
    raise TimeoutError("AI video generation timed out after 10 minutes")


# ── Provider implementations ──────────────────────────────────────────────────

def _generate_kling(prompt: str, duration: int, aspect_ratio: str,
                    output_name: str | None) -> str:
    import json
    key = LLM_CONFIG.get("kling_key", "")
    if not key:
        raise ValueError("Kling API key not set. Add it in Model Settings.")

    headers = {"Authorization": f"Bearer {key}"}
    body = json.dumps({
        "model":        "kling-v3",
        "prompt":       prompt,
        "duration":     str(duration),
        "aspect_ratio": aspect_ratio,
    }).encode()

    resp = _http_json("https://api.klingai.com/v1/videos/text2video",
                      method="POST", data=body, headers=headers)
    task_id = resp["data"]["task_id"]

    def check():
        r = _http_json(f"https://api.klingai.com/v1/videos/text2video/{task_id}",
                       headers=headers)
        status = r["data"]["task_status"]
        if status == "succeed":
            works = r["data"]["task_result"]["videos"]
            return works[0]["url"] if works else None
        if status == "failed":
            raise RuntimeError(f"Kling task failed: {r['data'].get('task_status_msg')}")
        return None

    url = _poll(check)
    return _save_video_from_url(url, output_name)


def _generate_luma(prompt: str, duration: int, aspect_ratio: str,
                   output_name: str | None) -> str:
    import json
    key = LLM_CONFIG.get("luma_key", "")
    if not key:
        raise ValueError("Luma API key not set. Add it in Model Settings.")

    headers = {"Authorization": f"Bearer {key}"}
    body = json.dumps({
        "prompt":       prompt,
        "aspect_ratio": aspect_ratio,
        "duration":     f"{duration}s",
    }).encode()

    resp = _http_json("https://api.lumalabs.ai/dream-machine/v1/generations",
                      method="POST", data=body, headers=headers)
    gen_id = resp["id"]

    def check():
        r = _http_json(f"https://api.lumalabs.ai/dream-machine/v1/generations/{gen_id}",
                       headers=headers)
        state = r.get("state")
        if state == "completed":
            return r["assets"]["video"]
        if state == "failed":
            raise RuntimeError(f"Luma generation failed: {r.get('failure_reason')}")
        return None

    url = _poll(check)
    return _save_video_from_url(url, output_name)


def _generate_runway(prompt: str, duration: int, aspect_ratio: str,
                     output_name: str | None) -> str:
    import json
    key = LLM_CONFIG.get("runway_key", "")
    if not key:
        raise ValueError("Runway API key not set. Add it in Model Settings.")

    # Map aspect_ratio to Runway ratio string
    ratio_map = {"9:16": "720:1280", "16:9": "1280:720", "1:1": "1080:1080"}
    ratio = ratio_map.get(aspect_ratio, "720:1280")

    headers = {"Authorization": f"Bearer {key}", "X-Runway-Version": "2024-11-06"}
    body = json.dumps({
        "model":       "gen4_turbo",
        "promptText":  prompt,
        "duration":    duration,
        "ratio":       ratio,
    }).encode()

    resp = _http_json("https://api.dev.runwayml.com/v1/text_to_video",
                      method="POST", data=body, headers=headers)
    task_id = resp["id"]

    def check():
        r = _http_json(f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
                       headers=headers)
        status = r.get("status")
        if status == "SUCCEEDED":
            outputs = r.get("output", [])
            return outputs[0] if outputs else None
        if status == "FAILED":
            raise RuntimeError(f"Runway task failed: {r.get('failure', {}).get('message')}")
        return None

    url = _poll(check)
    return _save_video_from_url(url, output_name)


def _generate_sora(prompt: str, duration: int, aspect_ratio: str,
                   output_name: str | None) -> str:
    key = LLM_CONFIG.get("openai_key", "")
    if not key:
        raise ValueError("OpenAI API key not set. Add it in Model Settings.")

    try:
        import openai
    except ImportError:
        raise ImportError("openai package required for Sora. Run: pip install openai")

    client = openai.OpenAI(api_key=key)

    # Map aspect_ratio to resolution
    res_map = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
    width, height = res_map.get(aspect_ratio, (1080, 1920))

    response = client.videos.generate(
        model="sora-1.0-hd",
        prompt=prompt,
        width=width,
        height=height,
        n_seconds=duration,
        n=1,
    )
    video_url = response.data[0].url
    return _save_video_from_url(video_url, output_name)


def _generate_wan(prompt: str, duration: int, aspect_ratio: str,
                  output_name: str | None) -> str:
    import json
    key = LLM_CONFIG.get("replicate_key", "")
    if not key:
        raise ValueError("Replicate API key not set. Add it in Model Settings (for Wan 2.5).")

    headers = {"Authorization": f"Token {key}"}
    body = json.dumps({
        "input": {
            "prompt":        prompt,
            "num_frames":    duration * 24,
            "aspect_ratio":  aspect_ratio,
        }
    }).encode()

    resp = _http_json(
        "https://api.replicate.com/v1/models/wavespeed-ai/wan2.1-t2v-720p/predictions",
        method="POST", data=body, headers=headers,
    )
    pred_id = resp["id"]

    def check():
        r = _http_json(f"https://api.replicate.com/v1/predictions/{pred_id}",
                       headers=headers)
        status = r.get("status")
        if status == "succeeded":
            output = r.get("output")
            return output[0] if isinstance(output, list) else output
        if status == "failed":
            raise RuntimeError(f"Replicate/Wan prediction failed: {r.get('error')}")
        return None

    url = _poll(check)
    return _save_video_from_url(url, output_name)


def _generate_veo(prompt: str, duration: int, aspect_ratio: str,
                  output_name: str | None) -> str:
    key = LLM_CONFIG.get("google_key", "")
    if not key:
        raise ValueError("Google API key not set. Add it in Model Settings (for Veo).")

    try:
        import google.genai as genai
        from google.genai import types as gtypes
    except ImportError:
        raise ImportError("google-genai package required for Veo. Run: pip install google-genai")

    client = genai.Client(api_key=key)

    operation = client.models.generate_video(
        model="veo-3.1-generate-preview",
        prompt=prompt,
        config=gtypes.GenerateVideoConfig(
            aspect_ratio=aspect_ratio,
            duration_seconds=duration,
            number_of_videos=1,
        ),
    )

    # Poll until done
    deadline = time.time() + 600
    while not operation.done and time.time() < deadline:
        time.sleep(5)
        operation = client.operations.get(operation)

    if not operation.done:
        raise TimeoutError("Veo generation timed out")

    video_bytes = operation.response.generated_videos[0].video.video_bytes
    fname = output_name or f"veo_{uuid.uuid4().hex[:8]}.mp4"
    if not fname.endswith(".mp4"):
        fname += ".mp4"
    dest = OUTPUT_DIR / fname
    dest.write_bytes(video_bytes)
    return str(dest)


# ── Public tool ───────────────────────────────────────────────────────────────

def generate_ai_video(
    prompt: str,
    provider: str = "kling",
    duration: int = 5,
    aspect_ratio: str = "9:16",
    output_name: str | None = None,
) -> dict:
    """
    Generate a video from a text prompt using a cloud AI video model.

    Returns:
        {"path": str, "provider": str}  on success
        {"error": str}  on failure
    """
    provider = provider.lower().strip()
    _gen_map = {
        "kling":     _generate_kling,
        "luma":      _generate_luma,
        "runway":    _generate_runway,
        "sora":      _generate_sora,
        "wan":       _generate_wan,
        "replicate": _generate_wan,
        "veo":       _generate_veo,
        "google":    _generate_veo,
    }
    fn = _gen_map.get(provider)
    if not fn:
        return {"error": f"Unknown provider '{provider}'. Choose from: kling, luma, runway, sora, wan, veo"}

    try:
        path = fn(prompt, duration, aspect_ratio, output_name)
        return {"path": path, "provider": provider}
    except (ValueError, RuntimeError, TimeoutError) as exc:
        return {"error": str(exc)}
