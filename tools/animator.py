"""
3D animation generation via Blender Python scripting.

Blender is run headlessly:
  blender --background --python <script.py> -- --output <dir> --frames <n>

Claude dynamically writes the Blender Python script based on the animation concept.
Built-in templates are provided for common viral content styles.

Requirements:
  brew install blender        # macOS
  sudo apt install blender    # Ubuntu/Debian
  Or download from blender.org

Verify: blender --version
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR, TEMP_DIR, ANIMATION_DURATION
from tools.llm import chat


# ── Blender executable detection ──────────────────────────────────────────────

def _find_blender() -> str:
    """Locate the Blender executable (cross-platform, handles versioned install dirs)."""
    import glob

    candidates = [
        shutil.which("blender"),
        # macOS
        "/Applications/Blender.app/Contents/MacOS/Blender",
        # Linux
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/snap/bin/blender",
    ]

    # Windows: versioned directories like "Blender 4.2", "Blender 3.6", etc.
    if platform.system() == "Windows":
        for pattern in [
            r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
            r"C:\Program Files (x86)\Blender Foundation\Blender*\blender.exe",
        ]:
            matches = sorted(glob.glob(pattern), reverse=True)  # newest version first
            candidates.extend(matches)

    for c in candidates:
        if c and Path(c).exists():
            return c
    raise FileNotFoundError(
        "Blender not found. Install from https://www.blender.org/download/ "
        "or on macOS: brew install blender"
    )


def _run_blender(script_path: str, extra_args: list[str] | None = None) -> str:
    """Run a Blender Python script headlessly. Returns stdout."""
    blender = _find_blender()
    cmd = [
        blender, "--background",
        "--python", script_path,
        "--",  # separator: everything after this goes to sys.argv in the script
        *(extra_args or []),
    ]
    print(f"🎨  Running Blender: {' '.join(cmd[:4])} …")
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    stdout = result.stdout.decode("utf-8", errors="ignore")
    stderr = result.stderr.decode("utf-8", errors="ignore")
    if result.returncode != 0:
        raise RuntimeError(f"Blender error:\n{stderr[-1000:]}")
    return stdout


# ── Main generation function ───────────────────────────────────────────────────

def generate_animation(
    prompt: str,
    image_path: str | None = None,
    duration: int | None = None,
    output_name: str | None = None,
    style: str = "epic cinematic",
    template: str | None = None,
) -> str:
    """
    Generate a 3D animation using Blender.

    prompt:   Describe what should happen in the animation
    style:    Visual style hint (passed to Claude for script generation)
    template: Optional preset – 'title_reveal', 'particle_explosion',
              'camera_flythrough', 'space_scene', 'abstract_geometric'
              If None, Claude writes a custom script.
    Returns: path to the rendered mp4.
    """
    dur      = duration or ANIMATION_DURATION
    out_name = output_name or f"animation_{abs(hash(prompt))}.mp4"
    out_path = str(OUTPUT_DIR / out_name)

    render_dir = str(TEMP_DIR / f"render_{abs(hash(prompt))}")
    Path(render_dir).mkdir(parents=True, exist_ok=True)

    if template:
        script = _get_template_script(template, prompt, dur, render_dir)
    else:
        script = _generate_blender_script(prompt, style, dur, render_dir)

    script_path = str(TEMP_DIR / f"bpy_{abs(hash(prompt))}.py")
    Path(script_path).write_text(script)

    blender_output = _run_blender(script_path)

    # Check frames were actually rendered
    rendered_frames = list(Path(render_dir).glob("frame_*.png"))
    if not rendered_frames:
        # Blender ran but produced no frames — likely a script error
        # Try once more with the space_scene template as fallback
        print("⚠️  No frames rendered — retrying with space_scene template")
        script = _get_template_script("space_scene", prompt, dur, render_dir)
        Path(script_path).write_text(script)
        _run_blender(script_path)
        rendered_frames = list(Path(render_dir).glob("frame_*.png"))
        if not rendered_frames:
            raise RuntimeError(
                f"Blender rendered 0 frames. Output:\n{blender_output[-800:]}"
            )

    # Combine PNG frames into mp4
    _frames_to_video(render_dir, out_path, fps=30)
    print(f"✅  Animation saved to {out_path}")
    return out_path


# ── Claude-generated Blender script ───────────────────────────────────────────

def _generate_blender_script(
    prompt: str,
    style: str,
    duration: int,
    render_dir: str,
) -> str:
    """Ask the local LLM to write a complete Blender Python script for the animation."""
    n_frames = duration * 30  # 30 fps

    system = """You are an expert Blender Python (bpy) developer who specialises in creating
cinematic, visually stunning short animations for viral social media content.
You write complete, self-contained Blender Python scripts that run headlessly."""

    prompt_text = f"""Write a complete Blender Python script (bpy) that creates this animation:

CONCEPT: {prompt}
STYLE: {style}
DURATION: {duration} seconds ({n_frames} frames at 30fps)
RENDER OUTPUT DIR: {render_dir}

Requirements:
1. Use bpy – runs in Blender's headless mode (--background)
2. Set render engine to EEVEE (fastest for headless rendering)
3. Resolution: 1080 x 1920 (portrait 9:16 for Instagram Reels)
4. Frame range: 1 to {n_frames}
5. Output: PNG frames to "{render_dir}/frame_####.png"
6. Include:
   - Camera with cinematic movement (dolly, orbit, or push)
   - Dramatic three-point lighting with coloured rim light
   - At least one animated object or particle system
   - Depth of field for cinematic feel
   - World HDRI-style background (procedural sky or gradient)
7. The scene must be VISUALLY SPECTACULAR for a viral social reel

Script must:
- Import bpy at the top
- Clear the default scene (delete default cube/light/camera)
- Set all scene/render settings
- Create all objects, materials, lights, and camera programmatically
- Set keyframes for all animations
- Call bpy.ops.render.render(animation=True) at the end

Return ONLY the complete Python script code, nothing else."""

    code = chat([
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt_text},
    ]).strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return code


# ── Built-in templates ────────────────────────────────────────────────────────

def _get_template_script(
    template: str,
    prompt: str,
    duration: int,
    render_dir: str,
) -> str:
    """Return a pre-built Blender script for a common animation style."""
    templates = {
        "title_reveal":        _template_title_reveal,
        "particle_explosion":  _template_particle_explosion,
        "space_scene":         _template_space_scene,
        "abstract_geometric":  _template_abstract_geometric,
        "camera_flythrough":   _template_camera_flythrough,
    }
    fn = templates.get(template)
    if fn is None:
        raise ValueError(f"Unknown template '{template}'. Choose from: {list(templates)}")
    return fn(prompt, duration, render_dir)


def _template_title_reveal(text: str, duration: int, render_dir: str) -> str:
    n = duration * 30
    return f'''
import bpy, math

scene = bpy.context.scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── Render settings ──────────────────────────────────────────────────────────
scene.render.engine          = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x    = 1080
scene.render.resolution_y    = 1920
scene.render.fps             = 30
scene.frame_start            = 1
scene.frame_end              = {n}
scene.render.filepath        = "{render_dir}/frame_"
scene.render.image_settings.file_format = 'PNG'

# ── Background gradient ───────────────────────────────────────────────────────
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.02, 0.02, 0.08, 1)
bg.inputs[1].default_value = 1.0

# ── Text object ──────────────────────────────────────────────────────────────
bpy.ops.object.text_add(location=(0, 0, 0))
txt = bpy.context.object
txt.data.body           = "{text[:40]}"
txt.data.align_x        = 'CENTER'
txt.data.align_y        = 'CENTER'
txt.data.size           = 0.8
txt.data.extrude        = 0.05
txt.data.bevel_depth    = 0.01

# Metallic gold material
mat = bpy.data.materials.new("Gold")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value    = (1.0, 0.75, 0.1, 1)
bsdf.inputs["Metallic"].default_value     = 0.95
bsdf.inputs["Roughness"].default_value    = 0.15
txt.data.materials.append(mat)

# Animate: scale from 0 to 1 (0→30f), hold, then glow pulse
txt.scale = (0, 0, 0)
txt.keyframe_insert("scale", frame=1)
txt.scale = (1, 1, 1)
txt.keyframe_insert("scale", frame=30)

# ── Particle system (sparkles) ────────────────────────────────────────────────
bpy.ops.mesh.primitive_plane_add(size=0.1, location=(0, 0, 0))
emitter = bpy.context.object
ps = emitter.modifiers.new("Sparkles", "PARTICLE_SYSTEM")
settings = ps.particle_system.settings
settings.count          = 200
settings.lifetime       = 40
settings.emit_from      = 'FACE'
settings.normal_factor  = 3.0
settings.render_type    = 'HALO'
settings.particle_size  = 0.05

# ── Key light ────────────────────────────────────────────────────────────────
bpy.ops.object.light_add(type='AREA', location=(3, -3, 5))
key = bpy.context.object
key.data.energy = 800
key.data.color  = (1.0, 0.9, 0.7)

# Rim light (blue)
bpy.ops.object.light_add(type='SPOT', location=(-3, 3, 2))
rim = bpy.context.object
rim.data.energy = 400
rim.data.color  = (0.2, 0.4, 1.0)

# ── Camera ───────────────────────────────────────────────────────────────────
bpy.ops.object.camera_add(location=(0, -4, 0))
cam = bpy.context.object
cam.rotation_euler = (math.radians(90), 0, 0)
scene.camera = cam
cam.data.lens = 50
cam.data.dof.use_dof = True
cam.data.dof.focus_distance = 4.0
cam.data.dof.aperture_fstop = 2.0

# Slow push-in
cam.location.y = -5
cam.keyframe_insert("location", frame=1)
cam.location.y = -3.5
cam.keyframe_insert("location", frame={n})

bpy.ops.render.render(animation=True)
'''


def _template_space_scene(concept: str, duration: int, render_dir: str) -> str:
    n = duration * 30
    return f'''
import bpy, math, random

scene = bpy.context.scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

scene.render.engine          = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x    = 1080
scene.render.resolution_y    = 1920
scene.render.fps             = 30
scene.frame_start            = 1
scene.frame_end              = {n}
scene.render.filepath        = "{render_dir}/frame_"
scene.render.image_settings.file_format = 'PNG'

# Deep space background
world = bpy.data.worlds.new("Space")
scene.world = world
world.use_nodes = True
nt  = world.node_tree
bg  = nt.nodes["Background"]
bg.inputs[0].default_value = (0.0, 0.0, 0.02, 1)

# Stars (icospheres scattered in a sphere)
rng = random.Random(42)
for _ in range(300):
    x = rng.uniform(-20, 20)
    y = rng.uniform(-20, 20)
    z = rng.uniform(-20, 20)
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.02, location=(x, y, z))
    s = bpy.context.object
    mat = bpy.data.materials.new("Star")
    mat.use_nodes = True
    em = mat.node_tree.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = rng.uniform(2, 8)
    em.inputs["Color"].default_value    = (1, 1, rng.uniform(0.8, 1), 1)
    mat.node_tree.links.new(em.outputs[0], mat.node_tree.nodes["Material Output"].inputs[0])
    s.data.materials.append(mat)

# Central planet
bpy.ops.mesh.primitive_uv_sphere_add(radius=1.5, location=(0, 0, 0))
planet = bpy.context.object
pm = bpy.data.materials.new("Planet")
pm.use_nodes = True
bsdf = pm.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.05, 0.2, 0.8, 1)
bsdf.inputs["Roughness"].default_value  = 0.6
planet.data.materials.append(pm)

# Orbit ring
bpy.ops.mesh.primitive_torus_add(
    location=(0, 0, 0),
    major_radius=2.2, minor_radius=0.05,
    rotation=(math.radians(20), 0, 0),
)
ring = bpy.context.object
rm = bpy.data.materials.new("Ring")
rm.use_nodes = True
em2 = rm.node_tree.nodes.new("ShaderNodeEmission")
em2.inputs["Color"].default_value    = (0.6, 0.8, 1.0, 1)
em2.inputs["Strength"].default_value = 3.0
rm.node_tree.links.new(em2.outputs[0], rm.node_tree.nodes["Material Output"].inputs[0])
ring.data.materials.append(rm)

# Rotate planet
planet.rotation_euler.z = 0
planet.keyframe_insert("rotation_euler", frame=1)
planet.rotation_euler.z = math.radians(360)
planet.keyframe_insert("rotation_euler", frame={n})

# Light
bpy.ops.object.light_add(type='SUN', location=(5, -5, 8))
sun = bpy.context.object
sun.data.energy = 3.0
sun.data.color  = (1.0, 0.9, 0.8)

# Camera orbit
bpy.ops.object.camera_add(location=(0, -6, 2))
cam = bpy.context.object
cam.rotation_euler = (math.radians(80), 0, 0)
scene.camera = cam
cam.data.lens = 35

cam.location = (0, -6, 2)
cam.keyframe_insert("location", frame=1)
cam.location = (4, -4.5, 3)
cam.keyframe_insert("location", frame={n})

bpy.ops.render.render(animation=True)
'''


def _template_particle_explosion(concept: str, duration: int, render_dir: str) -> str:
    n = duration * 30
    return f'''
import bpy, math

scene = bpy.context.scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

scene.render.engine       = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x = 1080
scene.render.resolution_y = 1920
scene.render.fps          = 30
scene.frame_start         = 1
scene.frame_end           = {n}
scene.render.filepath     = "{render_dir}/frame_"
scene.render.image_settings.file_format = 'PNG'

world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.0, 0.0, 0.0, 1)

# Emitter sphere
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3, location=(0, 0, 0))
em = bpy.context.object
ps = em.modifiers.new("Explode", "PARTICLE_SYSTEM")
s  = ps.particle_system.settings
s.count         = 5000
s.lifetime      = {n} // 2
s.frame_start   = 1
s.frame_end     = 10
s.emit_from     = 'FACE'
s.normal_factor = 8.0
s.effector_weights.gravity = 0
s.render_type   = 'HALO'
s.particle_size = 0.04

mat = bpy.data.materials.new("Fire")
mat.use_nodes = True
em2 = mat.node_tree.nodes.new("ShaderNodeEmission")
em2.inputs["Color"].default_value    = (1.0, 0.4, 0.05, 1)
em2.inputs["Strength"].default_value = 5.0
mat.node_tree.links.new(em2.outputs[0], mat.node_tree.nodes["Material Output"].inputs[0])
em.data.materials.append(mat)

bpy.ops.object.light_add(type='POINT', location=(0, 0, 0))
l = bpy.context.object
l.data.energy = 2000
l.data.color  = (1.0, 0.5, 0.1)

bpy.ops.object.camera_add(location=(0, -5, 0))
cam = bpy.context.object
cam.rotation_euler = (math.radians(90), 0, 0)
scene.camera = cam
cam.data.lens = 50

bpy.ops.render.render(animation=True)
'''


def _template_abstract_geometric(concept: str, duration: int, render_dir: str) -> str:
    n = duration * 30
    return f'''
import bpy, math

scene = bpy.context.scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

scene.render.engine       = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x = 1080
scene.render.resolution_y = 1920
scene.render.fps          = 30
scene.frame_start         = 1
scene.frame_end           = {n}
scene.render.filepath     = "{render_dir}/frame_"
scene.render.image_settings.file_format = 'PNG'

world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.01, 0.05, 1)

shapes = []
for i in range(8):
    angle = (2 * math.pi / 8) * i
    x = 1.5 * math.cos(angle)
    z = 1.5 * math.sin(angle)
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.3, location=(x, 0, z))
    obj = bpy.context.object
    mat = bpy.data.materials.new(f"M{{i}}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    hue = i / 8.0
    bsdf.inputs["Base Color"].default_value  = (hue, 1-hue, 0.8, 1)
    bsdf.inputs["Metallic"].default_value    = 0.9
    bsdf.inputs["Roughness"].default_value   = 0.1
    bsdf.inputs["Emission"].default_value    = (hue, 1-hue, 0.8, 1)
    bsdf.inputs["Emission Strength"].default_value = 2.0
    obj.data.materials.append(mat)
    obj.keyframe_insert("rotation_euler", frame=1)
    obj.rotation_euler.z = math.radians(360)
    obj.keyframe_insert("rotation_euler", frame={n})
    shapes.append(obj)

bpy.ops.object.light_add(type='AREA', location=(4, -4, 6))
bpy.context.object.data.energy = 500

bpy.ops.object.camera_add(location=(0, -6, 0))
cam = bpy.context.object
cam.rotation_euler = (math.radians(90), 0, 0)
scene.camera = cam

bpy.ops.render.render(animation=True)
'''


def _template_camera_flythrough(concept: str, duration: int, render_dir: str) -> str:
    n = duration * 30
    return f'''
import bpy, math

scene = bpy.context.scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

scene.render.engine       = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x = 1080
scene.render.resolution_y = 1920
scene.render.fps          = 30
scene.frame_start         = 1
scene.frame_end           = {n}
scene.render.filepath     = "{render_dir}/frame_"
scene.render.image_settings.file_format = 'PNG'

world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
sky = world.node_tree.nodes["Background"]
sky.inputs[0].default_value = (0.3, 0.5, 0.9, 1)

# Ground plane
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, -1))
gm = bpy.data.materials.new("Ground")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.1, 0.3, 0.1, 1)
bpy.context.object.data.materials.append(gm)

# City-like pillars
import random
rng = random.Random(7)
for i in range(30):
    h = rng.uniform(0.5, 4)
    x = rng.uniform(-15, 15)
    y = rng.uniform(-15, 15)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, h/2 - 1))
    obj = bpy.context.object
    obj.scale = (rng.uniform(0.3, 0.8), rng.uniform(0.3, 0.8), h)
    cm = bpy.data.materials.new(f"B{{i}}")
    cm.use_nodes = True
    v = rng.uniform(0.3, 0.8)
    cm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (v*0.6, v*0.7, v, 1)
    obj.data.materials.append(cm)

# Sun
bpy.ops.object.light_add(type='SUN', location=(10, -10, 15))
bpy.context.object.data.energy = 3.0

# Camera fly-through
bpy.ops.object.camera_add(location=(0, -12, 3))
cam = bpy.context.object
cam.rotation_euler = (math.radians(80), 0, 0)
scene.camera = cam
cam.data.dof.use_dof      = True
cam.data.dof.focus_distance = 10
cam.data.dof.aperture_fstop = 1.8

cam.location = (0, -12, 3)
cam.keyframe_insert("location", frame=1)
cam.location = (0, 0, 5)
cam.keyframe_insert("location", frame={n // 2})
cam.location = (8, 8, 8)
cam.keyframe_insert("location", frame={n})

bpy.ops.render.render(animation=True)
'''


# ── Frame → video assembly ─────────────────────────────────────────────────────

def _frames_to_video(render_dir: str, out_path: str, fps: int = 30) -> None:
    """Combine PNG frames rendered by Blender into an mp4 using ffmpeg."""
    frame_pattern = str(Path(render_dir) / "frame_%04d.png")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", frame_pattern,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame-combine error:\n{result.stderr[-600:]}")


# ── Prompt helper ──────────────────────────────────────────────────────────────

def craft_animation_prompt(
    concept: str,
    visual_style: str = "epic cinematic 3D, dramatic lighting, ultra HD",
) -> str:
    """Use the local LLM to refine a concept into a detailed Blender animation description."""
    return chat([{"role": "user", "content": f"""Describe a visually stunning Blender 3D animation for this concept:
CONCEPT: {concept}
STYLE: {visual_style}

Be specific about: objects, camera movement, lighting, colours, atmosphere.
Keep it under 150 words. Return only the description."""}]).strip()
