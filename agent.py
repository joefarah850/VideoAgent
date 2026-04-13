"""
AI Video Agent – uses litellm so the provider/model can be switched at runtime.
Supports Ollama (local), OpenAI, and Anthropic without any code changes.
"""
from __future__ import annotations

import json
import traceback
from typing import Any

from tools.llm import stream_completion
from tools.analyzer  import transcribe_video, find_viral_moments
from tools.editor    import extract_clip, add_captions, add_background_music, add_effects, compose_final_clip
from tools.voiceover import clone_voice, generate_voiceover, apply_voiceover, generate_viral_narration, list_voices
from tools.animator  import generate_animation, craft_animation_prompt
from tools.ideas     import generate_content_ideas, generate_video_script
from tools.premiere  import (
    premiere_get_project_info, premiere_create_sequence, premiere_import_clip,
    premiere_add_clip_to_timeline, premiere_add_text_caption,
    premiere_add_transition, premiere_export_sequence, premiere_run_jsx,
)
from tools.video_gen import generate_ai_video


# ── Tool definitions (OpenAI / Ollama function-calling format) ─────────────────
# "parameters" is the same JSON-schema object; we just rename from "input_schema".

_RAW_TOOLS = [
    {
        "name": "transcribe_video",
        "description": "Transcribe the audio of a video file into text segments with timestamps. Use this first before finding viral moments.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_path": {"type": "string", "description": "Absolute or relative path to the video file"},
            },
            "required": ["video_path"],
        },
    },
    {
        "name": "find_viral_moments",
        "description": "Analyse a transcription to find the top viral-worthy moments in a long video. Returns timestamped clip suggestions.",
        "parameters": {
            "type": "object",
            "properties": {
                "transcript_data": {"type": "object", "description": "The transcript_data dict returned by transcribe_video"},
                "num_clips": {"type": "integer", "description": "How many viral clips to find (default 5)", "default": 5},
                "style": {"type": "string", "description": "Target style e.g. 'dramatic and epic', 'funny', 'educational'", "default": "dramatic and epic"},
            },
            "required": ["transcript_data"],
        },
    },
    {
        "name": "extract_clip",
        "description": "Extract a time segment from a video file.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_path":  {"type": "string"},
                "start":       {"type": "number", "description": "Start time in seconds"},
                "end":         {"type": "number", "description": "End time in seconds"},
                "output_name": {"type": "string", "description": "Optional output filename"},
            },
            "required": ["video_path", "start", "end"],
        },
    },
    {
        "name": "add_captions",
        "description": "Burn subtitles/captions onto a video.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_path": {"type": "string"},
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "number"},
                            "end":   {"type": "number"},
                            "text":  {"type": "string"},
                        },
                    },
                    "description": "List of timed caption segments",
                },
                "font_size":   {"type": "integer", "default": 60},
                "font_color":  {"type": "string",  "default": "white"},
                "position":    {"type": "string",  "enum": ["bottom", "top", "center"], "default": "bottom"},
                "output_name": {"type": "string"},
            },
            "required": ["video_path", "segments"],
        },
    },
    {
        "name": "add_background_music",
        "description": "Mix background music under a video's existing audio.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_path":   {"type": "string"},
                "music_path":   {"type": "string", "description": "Path to music file (mp3/wav)"},
                "music_volume": {"type": "number", "description": "0.0-1.0, default 0.15"},
                "output_name":  {"type": "string"},
            },
            "required": ["video_path", "music_path"],
        },
    },
    {
        "name": "add_effects",
        "description": "Apply a visual effect to a video (zoom_in, fade_in_out, color_grade_epic).",
        "parameters": {
            "type": "object",
            "properties": {
                "video_path":  {"type": "string"},
                "effect":      {"type": "string", "enum": ["zoom_in", "fade_in_out", "color_grade_epic"], "default": "zoom_in"},
                "output_name": {"type": "string"},
            },
            "required": ["video_path"],
        },
    },
    {
        "name": "compose_final_clip",
        "description": "All-in-one composition: resize to vertical 9:16, merge voiceover, add captions and background music. Use this for the final polished output.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_path":     {"type": "string"},
                "voiceover_path": {"type": "string", "description": "Optional path to voiceover audio"},
                "captions": {
                    "type": "array",
                    "description": "Optional caption segments",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "number"},
                            "end":   {"type": "number"},
                            "text":  {"type": "string"},
                        },
                    },
                },
                "music_path":     {"type": "string", "description": "Optional background music path"},
                "music_volume":   {"type": "number", "default": 0.12},
                "output_name":    {"type": "string"},
            },
            "required": ["video_path"],
        },
    },
    {
        "name": "clone_voice",
        "description": "Upload audio samples to Voicebox to create a cloned voice profile. Returns the profile_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "audio_samples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of paths to audio sample files (wav/mp3)",
                },
                "voice_name": {"type": "string", "default": "MyVoice"},
            },
            "required": ["audio_samples"],
        },
    },
    {
        "name": "generate_voiceover",
        "description": "Generate a voiceover audio file from a script using the cloned voice in Voicebox.",
        "parameters": {
            "type": "object",
            "properties": {
                "script":      {"type": "string", "description": "The narration text to synthesise"},
                "profile_id":  {"type": "string", "description": "Voicebox profile_id (uses default if omitted)"},
                "output_name": {"type": "string"},
            },
            "required": ["script"],
        },
    },
    {
        "name": "apply_voiceover",
        "description": "Merge a voiceover audio file onto a video, optionally keeping original audio at low volume.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_path":            {"type": "string"},
                "voiceover_path":        {"type": "string"},
                "original_audio_volume": {"type": "number", "description": "0.0-1.0 (0 = fully replace)", "default": 0.2},
                "output_name":           {"type": "string"},
            },
            "required": ["video_path", "voiceover_path"],
        },
    },
    {
        "name": "generate_viral_narration",
        "description": "Write a compelling 30-60 second narration script for a viral short-form video.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "style": {"type": "string", "default": "dramatic and inspirational"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "generate_animation",
        "description": "Generate a 3D animation using Blender (headless). Choose a template or omit for a custom AI-written Blender script.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt":      {"type": "string", "description": "Text description of the animation scene"},
                "template":    {
                    "type": "string",
                    "enum": ["title_reveal", "particle_explosion", "space_scene", "abstract_geometric", "camera_flythrough"],
                    "description": "Use a pre-built template, or omit for fully custom AI-written Blender script",
                },
                "duration":    {"type": "integer", "description": "Duration in seconds", "default": 10},
                "output_name": {"type": "string"},
                "style":       {"type": "string", "default": "epic cinematic"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "list_voices",
        "description": "List all cloned voice profiles available in the local Voicebox instance.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "craft_animation_prompt",
        "description": "Craft an optimised text-to-video / Blender prompt for maximum visual impact.",
        "parameters": {
            "type": "object",
            "properties": {
                "concept":      {"type": "string", "description": "The concept or scene idea"},
                "visual_style": {"type": "string", "default": "epic cinematic 3D, dramatic lighting, volumetric fog, ultra HD"},
            },
            "required": ["concept"],
        },
    },
    {
        "name": "generate_content_ideas",
        "description": "Generate viral short-form video ideas for a given niche.",
        "parameters": {
            "type": "object",
            "properties": {
                "niche":           {"type": "string"},
                "num_ideas":       {"type": "integer", "default": 10},
                "target_platform": {"type": "string", "default": "Instagram Reels / TikTok"},
            },
            "required": ["niche"],
        },
    },
    {
        "name": "generate_video_script",
        "description": "Expand a content idea into a full timed script with b-roll prompts for animation generation. Pass the full idea object from generate_content_ideas as the 'idea' parameter.",
        "parameters": {
            "type": "object",
            "properties": {
                "idea": {
                    "type": "object",
                    "description": "The full idea dict returned by generate_content_ideas (contains title, hook, format, visual_concept etc.)",
                    "properties": {
                        "title":             {"type": "string"},
                        "hook":              {"type": "string"},
                        "format":            {"type": "string"},
                        "visual_concept":    {"type": "string"},
                        "script_outline":    {"type": "string"},
                        "estimated_virality":{"type": "string"},
                    },
                },
                "duration_seconds": {"type": "integer", "default": 45},
                "tone":             {"type": "string", "default": "inspirational and dramatic"},
            },
            "required": ["idea"],
        },
    },
    # ── AI video generation ───────────────────────────────────────────────────
    {
        "name": "generate_ai_video",
        "description": (
            "Generate a video from a text prompt using a cloud AI video model. "
            "Supported providers: kling (Kling 3.0), luma (Luma Dream Machine), "
            "runway (Runway Gen-4 Turbo), sora (OpenAI Sora 2), wan (Wan 2.5 via Replicate), "
            "veo (Google Veo 3.1). "
            "Use this when the user wants AI-generated footage rather than editing existing video."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed visual description of the video to generate",
                },
                "provider": {
                    "type": "string",
                    "enum": ["kling", "luma", "runway", "sora", "wan", "veo"],
                    "description": "Which AI video model to use",
                    "default": "kling",
                },
                "duration": {
                    "type": "integer",
                    "description": "Video duration in seconds (5-10 typical)",
                    "default": 5,
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["9:16", "16:9", "1:1"],
                    "description": "Video aspect ratio (9:16 for Reels/TikTok, 16:9 for YouTube)",
                    "default": "9:16",
                },
                "output_name": {
                    "type": "string",
                    "description": "Optional filename for the output video",
                },
            },
            "required": ["prompt"],
        },
    },
    # ── Premiere Pro tools ────────────────────────────────────────────────────
    {
        "name": "premiere_get_project_info",
        "description": "Get the current Premiere Pro project state: sequences, clips on the active timeline, project name. Call this first before doing any Premiere editing.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "premiere_create_sequence",
        "description": "Create a new sequence in Premiere Pro. Defaults to 1080x1920 portrait 30fps for Instagram Reels.",
        "parameters": {
            "type": "object",
            "properties": {
                "name":   {"type": "string", "description": "Sequence name"},
                "width":  {"type": "integer", "default": 1080},
                "height": {"type": "integer", "default": 1920},
                "fps":    {"type": "number",  "default": 30.0},
            },
            "required": ["name"],
        },
    },
    {
        "name": "premiere_import_clip",
        "description": "Import a media file (mp4, mov, wav, etc.) into the active Premiere Pro project.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the media file"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "premiere_add_clip_to_timeline",
        "description": "Place a media clip on the Premiere Pro timeline. Optionally trim with in/out points.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path":         {"type": "string"},
                "track":             {"type": "integer", "description": "Video track index (0 = V1)", "default": 0},
                "position_seconds":  {"type": "number",  "description": "Timeline position in seconds. -1 to append after last clip.", "default": -1},
                "in_point":          {"type": "number",  "description": "Clip in-point in seconds (optional)"},
                "out_point":         {"type": "number",  "description": "Clip out-point in seconds (optional)"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "premiere_add_text_caption",
        "description": "Add a text caption or title overlay to the Premiere Pro timeline at a specific time.",
        "parameters": {
            "type": "object",
            "properties": {
                "text":              {"type": "string"},
                "start_seconds":     {"type": "number"},
                "duration_seconds":  {"type": "number"},
                "track":             {"type": "integer", "default": 1},
                "position":          {"type": "string", "enum": ["bottom", "center", "top"], "default": "bottom"},
                "font_size":         {"type": "integer", "default": 72},
                "color_hex":         {"type": "string",  "default": "#ffffff"},
            },
            "required": ["text", "start_seconds", "duration_seconds"],
        },
    },
    {
        "name": "premiere_add_transition",
        "description": "Add a video transition between clips on the Premiere Pro timeline.",
        "parameters": {
            "type": "object",
            "properties": {
                "clip_index":        {"type": "integer", "description": "Index of the clip to add transition after"},
                "transition_type":   {"type": "string", "enum": ["cross_dissolve", "dip_to_black"], "default": "cross_dissolve"},
                "duration_seconds":  {"type": "number", "default": 0.5},
                "track":             {"type": "integer", "default": 0},
            },
            "required": ["clip_index"],
        },
    },
    {
        "name": "premiere_export_sequence",
        "description": "Export the active Premiere Pro sequence to a file via Adobe Media Encoder.",
        "parameters": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "Full path for the output mp4 file"},
                "preset":      {"type": "string", "description": "AME preset path (leave empty for H.264 match source)", "default": ""},
            },
            "required": ["output_path"],
        },
    },
    {
        "name": "premiere_run_jsx",
        "description": "Execute arbitrary ExtendScript (JSX) directly inside Premiere Pro. Use for complex operations not covered by other tools. The script must return a JSON string.",
        "parameters": {
            "type": "object",
            "properties": {
                "jsx_code": {"type": "string", "description": "Complete ExtendScript code to run inside Premiere Pro"},
            },
            "required": ["jsx_code"],
        },
    },
]

# Wrap in OpenAI function-calling envelope
TOOLS = [{"type": "function", "function": t} for t in _RAW_TOOLS]


# ── Tool dispatcher ────────────────────────────────────────────────────────────

TOOL_MAP: dict[str, Any] = {
    "transcribe_video":         transcribe_video,
    "find_viral_moments":       find_viral_moments,
    "extract_clip":             extract_clip,
    "add_captions":             add_captions,
    "add_background_music":     add_background_music,
    "add_effects":              add_effects,
    "compose_final_clip":       compose_final_clip,
    "clone_voice":              clone_voice,
    "generate_voiceover":       generate_voiceover,
    "apply_voiceover":          apply_voiceover,
    "generate_viral_narration": generate_viral_narration,
    "generate_animation":       generate_animation,
    "craft_animation_prompt":   craft_animation_prompt,
    "list_voices":              list_voices,
    "generate_content_ideas":       generate_content_ideas,
    "generate_video_script":        generate_video_script,
    "generate_ai_video":            generate_ai_video,
    # Premiere Pro
    "premiere_get_project_info":    premiere_get_project_info,
    "premiere_create_sequence":     premiere_create_sequence,
    "premiere_import_clip":         premiere_import_clip,
    "premiere_add_clip_to_timeline": premiere_add_clip_to_timeline,
    "premiere_add_text_caption":    premiere_add_text_caption,
    "premiere_add_transition":      premiere_add_transition,
    "premiere_export_sequence":     premiere_export_sequence,
    "premiere_run_jsx":             premiere_run_jsx,
}


def _parse_text_tool_calls(text: str) -> list[dict] | None:
    """
    Some local models (Ollama llama3.1, mistral, etc.) output tool calls as
    plain JSON text instead of using the function-calling API fields.
    Detects and parses these patterns so the agent can still execute them.

    Handles:
      {"name": "tool_name", "arguments": {...}}
      {"name": "tool_name", "parameters": {...}}
      [{"name": ...}, ...]   (multiple calls)
    """
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # Try finding JSON object/array inside a larger text blob
        for start_ch, end_ch in [('{', '}'), ('[', ']')]:
            s = text.find(start_ch)
            if s == -1:
                continue
            # find matching close
            depth = 0
            for i, ch in enumerate(text[s:], s):
                if ch == start_ch:
                    depth += 1
                elif ch == end_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[s:i+1])
                            break
                        except (json.JSONDecodeError, ValueError):
                            pass
            else:
                continue
            break
        else:
            return None

    # Normalise to list
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return None

    results = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        # Try every known key pattern for the function name
        name = (item.get("name") or item.get("tool") or item.get("function")
                or item.get("tool_name") or item.get("action"))
        # Some models put the name in "items" when they hallucinate a schema format
        if not name:
            name = item.get("items")
        # Args under various key names
        args = (item.get("arguments") or item.get("parameters") or item.get("params")
                or item.get("input") or item.get("args") or {})
        if not name:
            continue
        # name might be a dict like {"name": "tool_name"} from hallucinated schemas
        if isinstance(name, dict):
            name = name.get("name") or name.get("function")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if name not in TOOL_MAP:
            continue
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                args = {}
        if not isinstance(args, dict):
            args = {}
        results.append({"name": name, "arguments": args})

    return results if results else None


def _coerce_tool_input(tool_input: dict[str, Any]) -> dict[str, Any]:
    """
    Local models sometimes serialize nested objects as JSON strings.
    Walk the input and parse any string values that look like JSON objects/arrays.
    """
    result = {}
    for k, v in tool_input.items():
        if isinstance(v, str) and v.strip().startswith(("{", "[")):
            try:
                result[k] = json.loads(v)
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        result[k] = v
    return result


def _call_tool(name: str, tool_input: dict[str, Any]) -> Any:
    fn = TOOL_MAP.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        coerced = _coerce_tool_input(tool_input)
        # If generate_video_script is called with idea fields at the top level
        # instead of nested under "idea", wrap them automatically
        if name == "generate_video_script" and "idea" not in coerced:
            idea_keys = {"title", "hook", "format", "visual_concept", "script_outline",
                         "estimated_virality", "best_posting_time"}
            extracted = {k: coerced.pop(k) for k in list(coerced.keys()) if k in idea_keys}
            if extracted:
                coerced["idea"] = extracted
            elif "title" not in coerced:
                return {"error": "generate_video_script requires an 'idea' argument"}

        # If find_viral_moments is called without transcript_data, transcribe first
        if name == "find_viral_moments" and "transcript_data" not in coerced:
            video_path = coerced.pop("video_path", None)
            if video_path:
                from tools.analyzer import transcribe_video as _transcribe
                coerced["transcript_data"] = _transcribe(video_path)
            else:
                return {"error": "find_viral_moments requires transcript_data. Call transcribe_video first."}
        return fn(**coerced)
    except Exception as exc:
        traceback.print_exc()
        return {"error": str(exc)}


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert AI video production agent. You produce finished videos — you do not just describe or plan them.

== CORE RULE: ACT, DON'T ASK ==
When the user says "yes", "go ahead", "do it", "sure", "ok", or any affirmative — START EXECUTING IMMEDIATELY using your tools. Do not ask follow-up questions. Make sensible default choices:
- Format: portrait 9:16 (1080x1920) for Instagram Reels unless told otherwise
- Duration: 30-45 seconds per clip
- Style: dramatic and epic
- Captions: bold white text at the bottom
- If a video file was uploaded earlier in the conversation, use it

The ONLY time you may ask a question is when you are completely blocked — e.g. no video file has been provided and none exists to work with. In that case ask ONE short question to unblock yourself, then act immediately on the answer.

== ANIMATION PIPELINE (default for all animation requests) ==
  generate_video_script -> craft_animation_prompt -> generate_animation ->
  generate_voiceover (if Voicebox available) -> compose_final_clip
  Use this for ANY request involving 3D animation, Blender, or generating video from scratch.
  generate_animation uses Blender locally — no API key needed.

== AI VIDEO GENERATION (cloud, ONLY when user explicitly names a provider) ==
  craft_animation_prompt -> generate_ai_video(provider=kling|luma|runway|sora|wan|veo) ->
  compose_final_clip (optional: add captions/voiceover)
  ONLY use this when the user explicitly says "Kling", "Luma", "Runway", "Sora", "Wan", or "Veo".
  NEVER use generate_ai_video just because no other method is available — fall back to generate_animation instead.

== PREMIERE PRO EDITING PIPELINE (polish an existing full video) ==
Use this when the user wants to EDIT their video in Premiere (NOT extract viral clips):
  1. transcribe_video  ← to find bad takes / flubs / long pauses
  2. premiere_get_project_info
  3. premiere_create_sequence (name it after the video)
  4. premiere_import_clip
  5. premiere_add_clip_to_timeline for each good section using in_point/out_point to
     skip over bad takes, mistakes, and long silences identified from the transcript
  6. premiere_add_text_caption at key moments (highlight important phrases)
  7. premiere_add_transition between each section (cross_dissolve, 0.5s)
  8. premiere_export_sequence
Do NOT call find_viral_moments for this pipeline. You are editing the whole video,
not extracting short clips.

== VIRAL CLIPS PIPELINE (extract best short clips from a long video) ==
Use this ONLY when the user says "extract viral clips", "find viral moments", or
"make shorts from this video". Do NOT use for general Premiere editing.
If Premiere is connected:
  transcribe_video -> find_viral_moments -> premiere_get_project_info ->
  premiere_create_sequence -> [for each clip] premiere_import_clip +
  premiere_add_clip_to_timeline + premiere_add_text_caption +
  premiere_add_transition -> premiere_export_sequence

If Premiere is NOT connected (fallback):
  transcribe_video -> find_viral_moments -> extract_clip + add_captions -> compose_final_clip

== PREMIERE PRO TOOLS ==
premiere_get_project_info, premiere_create_sequence, premiere_import_clip,
premiere_add_clip_to_timeline (in_point/out_point for trimming),
premiere_add_text_caption, premiere_add_transition, premiere_export_sequence,
premiere_run_jsx (arbitrary JSX for anything else)

== OUTPUT RULES ==
- Report file paths after each tool completes
- Be brief — one sentence per step
- Never list plans or ask for approval mid-task

== CRITICAL: ALWAYS USE TOOLS ==
You MUST call tools to do any work. NEVER generate content, ideas, scripts, animations,
or file outputs yourself — always invoke the appropriate tool.
Examples:
- User wants video ideas → call generate_content_ideas
- User wants a script → call generate_video_script
- User wants an animation → call generate_animation
- User wants viral clips → call transcribe_video then find_viral_moments
If you generate content as plain text or JSON without calling a tool, that is WRONG.

== TOOL CALL FORMAT ==
When calling a tool, output ONLY this exact JSON, nothing else before or after:
{"name": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}
Do NOT wrap it in "type", "items", "function", "tool_calls", or any other key.
Do NOT add explanation text before or after the JSON when calling a tool.
"""


# ── Main agent loop ────────────────────────────────────────────────────────────

def run_agent(user_request: str, emit=None, history: list | None = None) -> str:
    """
    Run the AI Video Agent for a given user request.

    emit: optional callable(event_dict) for streaming to a UI.

    Event types:
      {"type": "text",        "content": str}
      {"type": "tool_call",   "tool_name": str, "tool_input": dict}
      {"type": "tool_result", "tool_name": str, "content": str, "is_file": bool, "file_path": str|None}
      {"type": "done",        "content": str}
      {"type": "error",       "content": str}
    """
    def _emit(event: dict):
        if emit:
            emit(event)
        else:
            t = event.get("type")
            if t == "text":
                print(f"\n🤖  {event['content']}", end="", flush=True)
            elif t == "tool_call":
                preview = json.dumps(event.get("tool_input", {}))[:120]
                print(f"\n🔧  {event['tool_name']}  {preview}")
            elif t == "tool_result":
                print(f"    ✅  {str(event['content'])[:200]}")
            elif t == "error":
                print(f"\n❌  {event['content']}")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_request})

    final_text = ""

    while True:
        # ── Stream via litellm (provider/model set in LLM_CONFIG) ──────────────
        stream = stream_completion(messages, tools=TOOLS)

        text_parts: list[str] = []
        # tool_calls collected across streamed chunks: index -> {id, name, arguments}
        tool_call_acc: dict[int, dict] = {}
        finish_reason = None

        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta  = choice.delta
            finish_reason = choice.finish_reason or finish_reason

            # Stream text tokens
            if delta.content:
                text_parts.append(delta.content)
                _emit({"type": "text", "content": delta.content})

            # Accumulate tool-call argument deltas
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_call_acc:
                        tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_call_acc[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_call_acc[idx]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_call_acc[idx]["arguments"] += tc.function.arguments

        assembled_text = "".join(text_parts)
        final_text = assembled_text or final_text

        # ── No structured tool calls – check if model wrote JSON tool call as text ──
        was_text_tool_call = False
        if not tool_call_acc:
            text_calls = _parse_text_tool_calls(assembled_text) if assembled_text else None
            if text_calls:
                was_text_tool_call = True
                for i, tc in enumerate(text_calls):
                    tool_call_acc[i] = {
                        "id":        f"text_call_{i}",
                        "name":      tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    }
            else:
                # Genuinely done – no tool calls found
                _emit({"type": "done", "content": assembled_text})
                return assembled_text

        # ── Execute tool calls ─────────────────────────────────────────────────
        # Reconstruct assistant message with tool_calls for the history
        assistant_tool_calls = []
        for idx in sorted(tool_call_acc.keys()):
            tc = tool_call_acc[idx]
            assistant_tool_calls.append({
                "id":       tc["id"] or f"call_{idx}",
                "type":     "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            })

        # Execute each tool and collect results
        # For text-based tool calls use plain user/assistant turns — local models
        # don't understand the structured tool role in history and start echoing it.
        if was_text_tool_call:
            tool_results_for_history = []

        if not was_text_tool_call:
            messages.append({
                "role":       "assistant",
                "content":    assembled_text or None,
                "tool_calls": assistant_tool_calls,
            })

        for tc_msg in assistant_tool_calls:
            fn_name = tc_msg["function"]["name"]
            try:
                tool_input = json.loads(tc_msg["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                tool_input = {}

            _emit({"type": "tool_call", "tool_name": fn_name, "tool_input": tool_input})

            result = _call_tool(fn_name, tool_input)

            if isinstance(result, (dict, list)):
                result_str = json.dumps(result, indent=2, default=str)
            else:
                result_str = str(result)

            is_file = (
                isinstance(result, str)
                and (result.startswith("/") or (len(result) > 2 and result[1] == ":"))
                and "." in result.split("/")[-1].split("\\")[-1]
            )

            _emit({
                "type":      "tool_result",
                "tool_name": fn_name,
                "content":   result_str[:2000],
                "is_file":   is_file,
                "file_path": result if is_file else None,
            })

            if was_text_tool_call:
                tool_results_for_history.append(
                    f"Tool `{fn_name}` result:\n{result_str[:3000]}"
                )
            else:
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc_msg["id"],
                    "content":      result_str,
                })

        # For text tool calls: inject results as a single user message so the
        # local model understands the context without seeing raw API formats
        if was_text_tool_call:
            combined = "\n\n---\n\n".join(tool_results_for_history)
            messages.append({"role": "assistant", "content": "(executed tools)"})
            messages.append({"role": "user", "content": (
                f"Tool results:\n\n{combined}\n\n"
                "IMPORTANT: Use these results to continue the task. "
                "If there are more tools to call, output the next tool call as JSON now. "
                "Do NOT repeat previous tool calls. Do NOT echo the results back. "
                "Do NOT output plain text unless all tools are done and you are giving the final answer."
            )})


    return final_text
