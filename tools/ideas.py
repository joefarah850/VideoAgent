"""
Content ideation – uses Claude to generate viral video ideas.
"""
from __future__ import annotations

import json
from typing import Any

from tools.llm import chat_json


def _coerce_idea(idea: Any) -> dict:
    """Ensure idea is a dict — local models sometimes pass it as a JSON string."""
    if isinstance(idea, dict):
        return idea
    if isinstance(idea, str):
        try:
            parsed = json.loads(idea)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        # Plain string — treat it as the title/concept
        return {"title": idea, "hook": "", "format": "", "visual_concept": idea}
    return {}


def generate_content_ideas(
    niche: str,
    num_ideas: int = 10,
    formats: list[str] | None = None,
    target_platform: str = "Instagram Reels / TikTok",
) -> list[dict[str, Any]]:
    """
    Generate viral short-form video ideas for a given niche.

    Returns a list of idea dicts:
      [{"title": str, "hook": str, "format": str, "script_outline": str, "visual_concept": str}, ...]
    """
    fmts = formats or [
        "talking head",
        "3D cinematic animation",
        "b-roll montage with voiceover",
        "split screen comparison",
        "dramatic reveal",
        "educational explainer",
    ]

    prompt = f"""You are a top viral content strategist for {target_platform}.

NICHE: {niche}
AVAILABLE FORMATS: {', '.join(fmts)}

Generate {num_ideas} viral short-form video ideas that would perform exceptionally well.

Focus on:
- Strong pattern-interrupting hooks (first 3 seconds)
- Emotional triggers: curiosity, awe, surprise, inspiration
- Trending topics within the niche
- Ideas that have shareability built in

Return ONLY a JSON array (no markdown):
[
  {{
    "title": "<punchy title>",
    "hook": "<first 5 seconds – what will viewers see/hear>",
    "format": "<chosen format>",
    "script_outline": "<3-5 bullet point outline>",
    "visual_concept": "<describe the visual style and key visuals>",
    "estimated_virality": "<low/medium/high/viral>",
    "best_posting_time": "<e.g. Tuesday 7pm EST>"
  }},
  ...
]"""

    return chat_json([{"role": "user", "content": prompt}])


def generate_video_script(
    idea: dict[str, Any],
    duration_seconds: int = 45,
    tone: str = "inspirational and dramatic",
) -> dict[str, Any]:
    """
    Expand a content idea into a full script with timed sections.

    Returns:
      {
        "script": str,                   # full narration text
        "sections": [{"time": "0:00-0:05", "action": str, "narration": str}, ...]
        "b_roll_prompts": [str, ...]     # animation/image prompts per section
      }
    """
    idea = _coerce_idea(idea)

    prompt = f"""Write a complete script for this {duration_seconds}-second viral video:

TITLE: {idea.get('title', '')}
HOOK: {idea.get('hook', '')}
FORMAT: {idea.get('format', '')}
VISUAL CONCEPT: {idea.get('visual_concept', '')}
TONE: {tone}

Structure it as timed sections.  Return ONLY JSON:
{{
  "script": "<full narration text to be spoken>",
  "sections": [
    {{
      "time": "0:00-0:05",
      "action": "<visual action or camera move>",
      "narration": "<exact words spoken>"
    }},
    ...
  ],
  "b_roll_prompts": [
    "<text-to-video prompt for section 1>",
    "<text-to-video prompt for section 2>",
    ...
  ]
}}"""

    return chat_json([{"role": "user", "content": prompt}])
