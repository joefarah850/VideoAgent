"""
Video editor – Premiere Pro automation via ExtendScript (cross-platform).

Workflow:
  1. Python extracts rough clips with ffmpeg (fast, lossless)
  2. Python generates a JSX ExtendScript that imports those clips into Premiere,
     creates sequences, adds captions, applies effects, and exports
  3. JSX is executed via osascript (macOS) or PowerShell COM (Windows)
  4. Final polished file lands in OUTPUT_DIR

Fallback: if Premiere is not running / not found, ffmpeg concat is used instead.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR, TEMP_DIR, CLIP_TARGET_FPS
from tools.llm import chat


# ── ffmpeg helpers ─────────────────────────────────────────────────────────────

def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-y", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{result.stderr[-800:]}")
    return result


# ── Core extraction (fast, lossless copy) ────────────────────────────────────

def extract_clip(
    video_path: str,
    start: float,
    end: float,
    output_name: str | None = None,
    lossless: bool = True,
) -> str:
    """
    Extract a time range from a video using ffmpeg.
    lossless=True uses stream-copy (instant); False re-encodes for frame-accuracy.
    Returns path to the extracted clip.
    """
    video_path = str(Path(video_path).resolve())
    out_name   = output_name or f"clip_{int(start)}_{int(end)}.mp4"
    out_path   = str(TEMP_DIR / out_name)
    duration   = end - start

    if lossless:
        _ffmpeg(
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c", "copy",
            out_path,
        )
    else:
        _ffmpeg(
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            out_path,
        )
    return out_path


def add_background_music(
    video_path: str,
    music_path: str,
    music_volume: float = 0.15,
    output_name: str | None = None,
) -> str:
    """Mix background music under the video audio using ffmpeg."""
    video_path = str(Path(video_path).resolve())
    music_path = str(Path(music_path).resolve())
    out_name   = output_name or f"music_{Path(video_path).stem}.mp4"
    out_path   = str(OUTPUT_DIR / out_name)

    _ffmpeg(
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac",
        out_path,
    )
    return out_path


def add_effects(
    video_path: str,
    effect: str = "zoom_in",
    output_name: str | None = None,
) -> str:
    """
    Apply a visual effect via ffmpeg filter.
    Supported: zoom_in, fade_in_out, color_grade_epic, vignette
    """
    video_path = str(Path(video_path).resolve())
    out_name   = output_name or f"{effect}_{Path(video_path).stem}.mp4"
    out_path   = str(OUTPUT_DIR / out_name)

    filters = {
        "zoom_in":         "scale=iw*2:ih*2,zoompan=z='min(zoom+0.002,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920",
        "fade_in_out":     "fade=t=in:st=0:d=0.5,fade=t=out:st=5:d=0.5",
        "color_grade_epic": "eq=contrast=1.15:brightness=-0.03:saturation=1.2,colorchannelmixer=rr=1.0:rb=0.03:gb=0.0:bb=1.05",
        "vignette":        "vignette=PI/4",
    }
    vf = filters.get(effect, "null")

    _ffmpeg(
        "-i", video_path,
        "-vf", vf,
        "-c:a", "copy",
        out_path,
    )
    return out_path


# ── Premiere Pro automation ────────────────────────────────────────────────────

def _premiere_is_running() -> bool:
    """Check if Premiere Pro is running (cross-platform)."""
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Adobe Premiere Pro"'],
                capture_output=True, text=True, timeout=5,
            )
            return "true" in result.stdout.lower()
        elif platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Adobe Premiere Pro.exe"],
                capture_output=True, text=True, timeout=5,
            )
            return "Adobe Premiere Pro" in result.stdout
        else:
            # Linux — check via pgrep
            result = subprocess.run(["pgrep", "-x", "premiere"], capture_output=True, timeout=5)
            return result.returncode == 0
    except Exception:
        return False


def _run_jsx_in_premiere(jsx_path: str) -> str:
    """Execute a JSX ExtendScript file inside running Premiere Pro (cross-platform)."""
    if platform.system() == "Darwin":
        script = f'''tell application "Adobe Premiere Pro"
    activate
    do script "{jsx_path}"
end tell'''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript error: {result.stderr}")
        return result.stdout.strip()
    elif platform.system() == "Windows":
        # Use PowerShell to invoke Premiere's COM automation
        ps_script = f'''
$premiere = [System.Runtime.InteropServices.Marshal]::GetActiveObject("Adobe.Premiere.Script")
$premiere.ExecuteScript("{jsx_path.replace(chr(92), chr(92)+chr(92))}")
'''
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"PowerShell/Premiere error: {result.stderr}")
        return result.stdout.strip()
    else:
        raise RuntimeError("Premiere Pro automation is only supported on macOS and Windows")


def generate_jsx_for_clips(
    clip_paths: list[str],
    clip_metadata: list[dict[str, Any]],
    output_path: str,
    sequence_name: str = "ViralClips",
) -> str:
    """
    Use Claude to write a Premiere Pro ExtendScript (JSX) that:
      - Imports the clips
      - Creates a new sequence (1080x1920 portrait, 30fps)
      - Places clips on the timeline
      - Adds titles/captions from metadata
      - Exports via AME or built-in encoder
    Returns the path to the saved .jsx file.
    """
    clips_info = []
    for i, (path, meta) in enumerate(zip(clip_paths, clip_metadata)):
        clips_info.append({
            "index": i,
            "path": path,
            "title": meta.get("suggested_title", f"Clip {i+1}"),
            "caption": meta.get("suggested_caption", ""),
            "hook": meta.get("hook", ""),
        })

    prompt = f"""Write a complete Adobe Premiere Pro ExtendScript (JSX) that does the following:

CLIPS TO IMPORT:
{json.dumps(clips_info, indent=2)}

OUTPUT PATH: {output_path}
SEQUENCE NAME: {sequence_name}
SEQUENCE SETTINGS: 1080x1920, 30fps (vertical / portrait for Instagram Reels)

The script must:
1. Get or create a project
2. Import each clip file using importFiles()
3. Create a new sequence with the portrait settings above
4. Place each clip on the timeline sequentially on Video Track 1
5. For each clip, add a text title using a Motion Graphics Template or TextMcBlob with the clip's 'title' overlaid at the bottom third
6. Add a 0.5s cross-dissolve transition between clips
7. Export the sequence to "{output_path}" as H.264 MP4 at high quality

Important Premiere Pro API notes:
- Use app.project, app.project.importFiles(), app.project.createNewSequence()
- Sequence.videoTracks[0].insertClip() for adding clips
- ClipProjectItem for transitions
- app.encoder.encodeSequence() or AMEBatchEncoding for export
- Handle errors gracefully with try/catch

Return only the complete JSX code, no explanation."""

    jsx_code = chat([{"role": "user", "content": prompt}]).strip()
    # Strip markdown if present
    if jsx_code.startswith("```"):
        jsx_code = jsx_code.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    jsx_path = str(TEMP_DIR / f"{sequence_name}.jsx")
    Path(jsx_path).write_text(jsx_code)
    return jsx_path


def edit_in_premiere(
    clip_paths: list[str],
    clip_metadata: list[dict[str, Any]],
    output_name: str = "premiere_export.mp4",
) -> str:
    """
    High-level function: generate JSX and run it in Premiere Pro.
    Falls back to ffmpeg concat if Premiere is not running.
    Returns path to the final output file.
    """
    out_path = str(OUTPUT_DIR / output_name)

    if _premiere_is_running():
        print("🎬  Premiere Pro detected – generating ExtendScript…")
        jsx_path = generate_jsx_for_clips(clip_paths, clip_metadata, out_path)
        print(f"    JSX saved to: {jsx_path}")
        _run_jsx_in_premiere(jsx_path)
        print(f"✅  Premiere export triggered → {out_path}")
    else:
        print("⚠️   Premiere Pro not running – falling back to ffmpeg concat…")
        out_path = _ffmpeg_concat(clip_paths, out_path)

    return out_path


def _ffmpeg_concat(clip_paths: list[str], out_path: str) -> str:
    """Concatenate clips with ffmpeg as a Premiere fallback."""
    list_file = str(TEMP_DIR / "concat_list.txt")
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    _ffmpeg(
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        out_path,
    )
    return out_path


# ── Caption burning (ffmpeg drawtext) ─────────────────────────────────────────

def add_captions(
    video_path: str,
    segments: list[dict[str, Any]],
    font_size: int = 60,
    font_color: str = "white",
    output_name: str | None = None,
    position: str = "bottom",
) -> str:
    """
    Burn subtitles using ffmpeg drawtext filter.
    segments: [{"start": float, "end": float, "text": str}]
    Returns path to the captioned video.
    """
    import re

    video_path = str(Path(video_path).resolve())
    out_name   = output_name or f"captioned_{Path(video_path).stem}.mp4"
    out_path   = str(OUTPUT_DIR / out_name)

    y_pos = "h-200" if position == "bottom" else ("100" if position == "top" else "(h-th)/2")

    # Build a drawtext filter for each segment
    filters = []
    for seg in segments:
        safe_text = re.sub(r"[\\':()]", lambda m: "\\" + m.group(), seg["text"])
        safe_text = safe_text.replace("\n", " ")
        t0 = seg["start"]
        t1 = seg["end"]
        filters.append(
            f"drawtext=text='{safe_text}'"
            f":fontsize={font_size}:fontcolor={font_color}"
            f":borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y={y_pos}"
            f":enable='between(t,{t0},{t1})'"
        )

    vf = ",".join(filters) if filters else "null"

    _ffmpeg(
        "-i", video_path,
        "-vf", vf,
        "-c:a", "copy",
        out_path,
    )
    return out_path


# ── Final composition ──────────────────────────────────────────────────────────

def compose_final_clip(
    video_path: str,
    voiceover_path: str | None = None,
    captions: list[dict] | None = None,
    music_path: str | None = None,
    music_volume: float = 0.12,
    target_resolution: tuple[int, int] = (1080, 1920),
    output_name: str | None = None,
) -> str:
    """
    All-in-one: resize to 9:16 portrait, merge voiceover, captions, background music.
    Uses ffmpeg filters for speed. Returns path to final clip.
    """
    video_path = str(Path(video_path).resolve())
    out_name   = output_name or f"final_{Path(video_path).stem}.mp4"
    out_path   = str(OUTPUT_DIR / out_name)
    tw, th     = target_resolution

    # Step 1: resize / crop to portrait
    resized = str(TEMP_DIR / f"resized_{Path(video_path).stem}.mp4")
    _ffmpeg(
        "-i", video_path,
        "-vf", f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}",
        "-c:a", "copy",
        resized,
    )

    # Step 2: build audio mix
    current = resized
    if voiceover_path or music_path:
        audio_inputs = ["-i", current]
        filter_parts = []
        map_args     = ["-map", "0:v"]
        audio_idx    = 1

        if voiceover_path:
            audio_inputs += ["-i", str(voiceover_path)]
            filter_parts.append(f"[{audio_idx}:a]volume=1.0[vo]")
            audio_idx += 1
        if music_path:
            audio_inputs += ["-i", str(music_path)]
            filter_parts.append(f"[{audio_idx}:a]volume={music_volume}[bg]")
            audio_idx += 1

        # Determine mix inputs
        mix_inputs = "[0:a]"
        if voiceover_path:
            mix_inputs += "[vo]"
        if music_path:
            mix_inputs += "[bg]"

        n_inputs = 1 + (1 if voiceover_path else 0) + (1 if music_path else 0)
        filter_parts.append(f"{mix_inputs}amix=inputs={n_inputs}:duration=first[aout]")

        mixed = str(TEMP_DIR / f"mixed_{Path(video_path).stem}.mp4")
        _ffmpeg(
            *audio_inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            mixed,
        )
        current = mixed

    # Step 3: burn captions
    if captions:
        current = add_captions(current, captions, output_name=f"cc_{Path(video_path).stem}.mp4")

    # Step 4: copy to final output
    if current != out_path:
        import shutil
        shutil.copy2(current, out_path)

    return out_path
