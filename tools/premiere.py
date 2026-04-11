"""
Premiere Pro editing tools.

The agent calls these functions; they forward JSX to the CEP panel via WebSocket
and return the result. All actual editing happens inside Premiere Pro.
"""
from __future__ import annotations

import json
from tools import premiere_bridge as _bridge


def _jsx(code: str, timeout: float = 60.0) -> str:
    """Execute JSX in Premiere Pro and return the raw result string."""
    return _bridge.run_jsx_sync(code, timeout=timeout)


def _jsx_json(code: str, timeout: float = 60.0) -> dict | list:
    raw = _jsx(code, timeout=timeout)
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


# ── Info ──────────────────────────────────────────────────────────────────────

def premiere_get_project_info() -> dict:
    """
    Get the current state of the open Premiere Pro project:
    sequences, clips in the active sequence, project name.
    """
    return _jsx_json("""(function() {
  try {
    var proj = app.project;
    var seqs = [];
    for (var i = 0; i < proj.sequences.numSequences; i++) {
      var s = proj.sequences[i];
      seqs.push({ id: s.sequenceID, name: s.name,
                  duration: parseFloat(s.end) / parseFloat(s.timebase) });
    }
    var active = proj.activeSequence;
    var clips = [];
    if (active) {
      var vt = active.videoTracks[0];
      for (var j = 0; j < vt.clips.numItems; j++) {
        var c = vt.clips[j];
        clips.push({ name: c.name,
                     start: parseFloat(c.start.seconds),
                     end:   parseFloat(c.end.seconds),
                     media: c.projectItem ? c.projectItem.getMediaPath() : "" });
      }
    }
    return JSON.stringify({
      project:        proj.name,
      sequences:      seqs,
      activeSequence: active ? active.name : null,
      clips:          clips
    });
  } catch(e) { return JSON.stringify({ error: e.toString() }); }
})();""")


# ── Sequence ──────────────────────────────────────────────────────────────────

def premiere_create_sequence(
    name: str,
    width: int = 1080,
    height: int = 1920,
    fps: float = 30.0,
) -> dict:
    """
    Create a new sequence in the active Premiere Pro project.
    Defaults to 1080×1920 portrait 30fps (Instagram Reels).
    """
    return _jsx_json(f"""(function() {{
  try {{
    var seqName = {json.dumps(name)};
    var newSeq  = app.project.createNewSequence(seqName, "seq-" + (new Date().getTime()));
    var settings = newSeq.getSettings();
    settings.videoFrameRate  = new Time();
    settings.videoFrameRate.seconds = 1.0 / {fps};
    settings.videoFrameWidth  = {width};
    settings.videoFrameHeight = {height};
    newSeq.setSettings(settings);
    app.project.activeSequence = newSeq;
    return JSON.stringify({{ success: true, sequenceID: newSeq.sequenceID, name: seqName }});
  }} catch(e) {{ return JSON.stringify({{ error: e.toString() }}); }}
}})();""")


# ── Import & timeline ─────────────────────────────────────────────────────────

def premiere_import_clip(file_path: str) -> dict:
    """Import a media file into the active Premiere Pro project."""
    return _jsx_json(f"""(function() {{
  try {{
    var path = {json.dumps(file_path)};
    app.project.importFiles([path], true, app.project.rootItem, false);
    var items = app.project.rootItem.findItemsMatchingMediaPath(path, true);
    var id = items && items.length ? items[0].nodeId : null;
    return JSON.stringify({{ success: true, nodeId: id, path: path }});
  }} catch(e) {{ return JSON.stringify({{ error: e.toString() }}); }}
}})();""")


def premiere_add_clip_to_timeline(
    file_path: str,
    track: int = 0,
    position_seconds: float = -1,
    in_point: float | None = None,
    out_point: float | None = None,
) -> dict:
    """
    Add a media file to the active sequence's video timeline.
    position_seconds=-1 appends after the last clip.
    in_point/out_point trim the clip (seconds).
    """
    in_s  = json.dumps(in_point)
    out_s = json.dumps(out_point)
    return _jsx_json(f"""(function() {{
  try {{
    var seq  = app.project.activeSequence;
    var path = {json.dumps(file_path)};
    var items = app.project.rootItem.findItemsMatchingMediaPath(path, true);
    if (!items || items.length === 0) {{
      app.project.importFiles([path], true, app.project.rootItem, false);
      items = app.project.rootItem.findItemsMatchingMediaPath(path, true);
    }}
    if (!items || items.length === 0) return JSON.stringify({{ error: "Could not find/import: " + path }});
    var item  = items[0];
    var vt    = seq.videoTracks[{track}];
    var pos   = {position_seconds};
    if (pos < 0) {{
      // Append after last clip
      var last = 0;
      for (var i = 0; i < vt.clips.numItems; i++) {{
        var e = parseFloat(vt.clips[i].end.seconds);
        if (e > last) last = e;
      }}
      pos = last;
    }}
    var posTime = new Time();
    posTime.seconds = pos;
    vt.insertClip(item, posTime);
    // Trim in/out if provided
    var inP = {in_s}, outP = {out_s};
    if (inP !== null || outP !== null) {{
      var added = vt.clips[vt.clips.numItems - 1];
      if (inP !== null)  {{ var t = new Time(); t.seconds = inP;  added.inPoint  = t; }}
      if (outP !== null) {{ var t = new Time(); t.seconds = outP; added.outPoint = t; }}
    }}
    return JSON.stringify({{ success: true, position: pos }});
  }} catch(e) {{ return JSON.stringify({{ error: e.toString() }}); }}
}})();""")


def premiere_add_text_caption(
    text: str,
    start_seconds: float,
    duration_seconds: float,
    track: int = 1,
    position: str = "bottom",
    font_size: int = 72,
    color_hex: str = "#ffffff",
) -> dict:
    """
    Add a text caption/title to the sequence at a specific time.
    position: 'bottom' | 'top' | 'center'
    """
    y_map = {"bottom": 1750, "center": 960, "top": 170}
    y = y_map.get(position, 1750)
    r = int(color_hex[1:3], 16) / 255.0
    g = int(color_hex[3:5], 16) / 255.0
    b = int(color_hex[5:7], 16) / 255.0
    return _jsx_json(f"""(function() {{
  try {{
    var seq   = app.project.activeSequence;
    var title = app.project.createNewTitle({json.dumps(text)});
    var doc   = title.getTitleDoc();
    var frame = doc.createTextFrame({json.dumps(text)});
    frame.setPosition(540, {y});
    frame.setFontSize({font_size});
    frame.setFillColor({{ red:{r:.3f}, green:{g:.3f}, blue:{b:.3f} }});
    frame.setTextAlignment(TitleTextAlignment.CENTER);
    var vt  = seq.videoTracks[{track}];
    var pos = new Time(); pos.seconds = {start_seconds};
    vt.insertClip(title, pos);
    var added = vt.clips[vt.clips.numItems - 1];
    var dur = new Time(); dur.seconds = {duration_seconds};
    added.end = new Time(); added.end.seconds = {start_seconds} + {duration_seconds};
    return JSON.stringify({{ success: true, text: {json.dumps(text)} }});
  }} catch(e) {{ return JSON.stringify({{ error: e.toString() }}); }}
}})();""")


def premiere_add_transition(
    clip_index: int,
    transition_type: str = "cross_dissolve",
    duration_seconds: float = 0.5,
    track: int = 0,
) -> dict:
    """
    Add a transition between clips on the timeline.
    transition_type: 'cross_dissolve' | 'dip_to_black'
    """
    preset_map = {
        "cross_dissolve": "Video Transitions/Dissolve/Cross Dissolve",
        "dip_to_black":   "Video Transitions/Dissolve/Dip to Black",
    }
    preset = preset_map.get(transition_type, preset_map["cross_dissolve"])
    return _jsx_json(f"""(function() {{
  try {{
    var seq  = app.project.activeSequence;
    var vt   = seq.videoTracks[{track}];
    var clip = vt.clips[{clip_index}];
    if (!clip) return JSON.stringify({{ error: "No clip at index {clip_index}" }});
    var dur = new Time(); dur.seconds = {duration_seconds};
    qe.project.getActiveSequence().getVideoTrackAt({track})
      .getClipAt({clip_index}).addTransition({json.dumps(preset)}, dur, false);
    return JSON.stringify({{ success: true }});
  }} catch(e) {{
    // Fallback: try via app.project.activeSequence clip transition API
    return JSON.stringify({{ warning: "Transition API not available: " + e.toString() }});
  }}
}})();""")


def premiere_export_sequence(
    output_path: str,
    preset: str = "",
) -> dict:
    """
    Export the active sequence to a file via Adobe Media Encoder.
    output_path: full path for the output mp4.
    preset: AME preset path (empty = H.264 match source).
    """
    return _jsx_json(f"""(function() {{
  try {{
    var seq    = app.project.activeSequence;
    var outPath = {json.dumps(output_path)};
    app.encoder.encodeSequence(
      seq, outPath, {json.dumps(preset)},
      app.encoder.ENCODE_IN_TO_OUT, false
    );
    return JSON.stringify({{ success: true, output_path: outPath }});
  }} catch(e) {{ return JSON.stringify({{ error: e.toString() }}); }}
}})();""")


# ── Escape hatch: arbitrary JSX ────────────────────────────────────────────────

def premiere_run_jsx(jsx_code: str) -> str:
    """
    Execute arbitrary ExtendScript (JSX) inside Premiere Pro.
    Use this for anything not covered by the specific tools above.
    The script should return a JSON string.
    Timeout is extended to 120s for complex operations.
    """
    return _jsx(jsx_code, timeout=120.0)
