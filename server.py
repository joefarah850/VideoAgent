"""
AI Video Agent – FastAPI web server.

Start with:  python server.py
Then open:   http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import platform
import shutil
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import run_agent
from config import OUTPUT_DIR, TEMP_DIR
from tools.system_check import get_capabilities
from tools.llm import LLM_CONFIG, MODEL_CATALOGUE
import tools.premiere_bridge as _premiere_bridge

# ── Lifespan: start Voicebox if installed ─────────────────────────────────────

_voicebox_proc: subprocess.Popen | None = None

def _start_voicebox() -> None:
    """Start Voicebox in the background if the cloned repo exists."""
    global _voicebox_proc
    voicebox_dir = Path(__file__).parent / "voicebox"
    if not voicebox_dir.exists():
        return
    just = shutil.which("just")
    if not just:
        return
    try:
        _voicebox_proc = subprocess.Popen(
            [just, "dev"],
            cwd=str(voicebox_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"🎙️  Voicebox started (pid {_voicebox_proc.pid})")
    except Exception as exc:
        print(f"⚠️  Could not start Voicebox: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Store event loop for the Premiere bridge
    _premiere_bridge.set_loop(asyncio.get_running_loop())
    # Start Voicebox
    _start_voicebox()
    yield
    # Shutdown
    if _voicebox_proc and _voicebox_proc.poll() is None:
        _voicebox_proc.terminate()


app      = FastAPI(title="AI Video Agent", lifespan=lifespan)
executor = ThreadPoolExecutor(max_workers=4)

# Active WebSocket sessions: session_id -> asyncio.Queue
_sessions: dict[str, asyncio.Queue] = {}

# Conversation histories: conversation_id -> list of {role, content} dicts
_conversations: dict[str, list] = {}


# ── REST: chat ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None   # omit to start a new conversation


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Start an agent run. Returns session_id and conversation_id."""
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _sessions[session_id] = queue

    # Reuse or create conversation history
    conv_id = req.conversation_id or str(uuid.uuid4())
    if conv_id not in _conversations:
        _conversations[conv_id] = []
    history = _conversations[conv_id]

    loop = asyncio.get_event_loop()

    def emit(event: dict):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def _run():
        try:
            reply = run_agent(req.message, emit=emit, history=history)
            # Persist the new turns into history
            history.append({"role": "user",      "content": req.message})
            history.append({"role": "assistant",  "content": reply})
            # Cap history at last 20 turns to avoid blowing context
            if len(history) > 40:
                _conversations[conv_id] = history[-40:]
        except Exception as exc:
            emit({"type": "error", "content": str(exc)})

    loop.run_in_executor(executor, _run)
    return {"session_id": session_id, "conversation_id": conv_id}


# ── WebSocket: Premiere Pro CEP panel bridge ─────────────────────────────────
# IMPORTANT: must be defined BEFORE /ws/{session_id} or FastAPI matches it wrong

@app.websocket("/ws/premiere")
async def premiere_ws(ws: WebSocket):
    """
    Persistent connection held by the Premiere Pro CEP panel.
    Server sends: {"id": "...", "jsx": "..."}
    Panel replies: {"id": "...", "result": "..."} or {"id": "...", "error": "..."}
    """
    await ws.accept()
    _premiere_bridge.set_panel(ws)
    print("🎬  Premiere Pro panel connected")
    try:
        while True:
            data = await ws.receive_json()
            # Handle keepalive ping from panel
            if data.get("ping"):
                await ws.send_json({"pong": True})
                continue
            req_id = data.get("id")
            if req_id:
                _premiere_bridge.resolve(
                    req_id,
                    result=data.get("result"),
                    error=data.get("error"),
                )
    except WebSocketDisconnect:
        pass
    finally:
        _premiere_bridge.clear_panel()
        print("🎬  Premiere Pro panel disconnected")


# ── WebSocket: stream agent events ────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    await ws.accept()
    queue = _sessions.get(session_id)
    if queue is None:
        await ws.send_json({"type": "error", "content": "Invalid session"})
        await ws.close()
        return

    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=300)
            await ws.send_json(event)
            if event.get("type") in ("done", "error"):
                break
    except asyncio.TimeoutError:
        await ws.send_json({"type": "error", "content": "Session timed out"})
    except WebSocketDisconnect:
        pass
    finally:
        _sessions.pop(session_id, None)


# ── REST: capability status ───────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """Return which tools/APIs are available on this machine."""
    return get_capabilities()


# ── REST: LLM config ──────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Return current LLM config and model catalogue."""
    return {
        "current": {
            "agent_provider":  LLM_CONFIG["agent_provider"],
            "agent_model":     LLM_CONFIG["agent_model"],
            "tasks_provider":  LLM_CONFIG["tasks_provider"],
            "tasks_model":     LLM_CONFIG["tasks_model"],
            "has_openai_key":     bool(LLM_CONFIG["openai_key"]),
            "has_anthropic_key":  bool(LLM_CONFIG["anthropic_key"]),
            "has_kling_key":      bool(LLM_CONFIG["kling_key"]),
            "has_luma_key":       bool(LLM_CONFIG["luma_key"]),
            "has_runway_key":     bool(LLM_CONFIG["runway_key"]),
            "has_replicate_key":  bool(LLM_CONFIG["replicate_key"]),
            "has_google_key":     bool(LLM_CONFIG["google_key"]),
        },
        "catalogue": MODEL_CATALOGUE,
    }


class ConfigSaveRequest(BaseModel):
    agent_provider: str
    agent_model: str
    tasks_provider: str
    tasks_model: str
    openai_key: str = ""
    anthropic_key: str = ""
    kling_key: str = ""
    luma_key: str = ""
    runway_key: str = ""
    replicate_key: str = ""
    google_key: str = ""


@app.post("/api/config")
async def save_config(req: ConfigSaveRequest):
    """Update active LLM config and persist to .env."""
    for p in (req.agent_provider, req.tasks_provider):
        if p not in ("ollama", "openai", "anthropic"):
            raise HTTPException(status_code=400, detail=f"Invalid provider: {p}")

    LLM_CONFIG["agent_provider"] = req.agent_provider
    LLM_CONFIG["agent_model"]    = req.agent_model
    LLM_CONFIG["tasks_provider"] = req.tasks_provider
    LLM_CONFIG["tasks_model"]    = req.tasks_model

    optional_keys = {
        "openai_key":    ("OPENAI_API_KEY",    req.openai_key),
        "anthropic_key": ("ANTHROPIC_API_KEY", req.anthropic_key),
        "kling_key":     ("KLING_API_KEY",     req.kling_key),
        "luma_key":      ("LUMA_API_KEY",      req.luma_key),
        "runway_key":    ("RUNWAY_API_KEY",    req.runway_key),
        "replicate_key": ("REPLICATE_API_KEY", req.replicate_key),
        "google_key":    ("GOOGLE_API_KEY",    req.google_key),
    }
    env_updates: dict[str, str] = {
        "AGENT_LLM_PROVIDER": req.agent_provider,
        "AGENT_LLM_MODEL":    req.agent_model,
        "TASKS_LLM_PROVIDER": req.tasks_provider,
        "TASKS_LLM_MODEL":    req.tasks_model,
    }
    for cfg_key, (env_key, value) in optional_keys.items():
        if value:
            LLM_CONFIG[cfg_key] = value
            env_updates[env_key] = value

    _write_env(env_updates)
    return {"ok": True}


@app.post("/api/config/pull")
async def pull_ollama_model(req: dict):
    """Pull an Ollama model. Returns SSE stream."""
    model = req.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="model required")

    async def _stream():
        proc = await asyncio.create_subprocess_exec(
            "ollama", "pull", model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            text = line.decode(errors="ignore").rstrip()
            if text:
                yield f"data: {json.dumps({'msg': text})}\n\n"
        await proc.wait()
        status = "ok" if proc.returncode == 0 else "error"
        yield f"data: {json.dumps({'done': True, 'status': status})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _write_env(updates: dict[str, str]) -> None:
    """Merge key=value pairs into .env (create if missing)."""
    env_path = Path(__file__).parent / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    existing_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                existing_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n")


# ── SSE: one-click setup ───────────────────────────────────────────────────────

@app.get("/api/setup")
async def setup_environment():
    """
    Stream setup progress as Server-Sent Events.
    Installs Ollama (if needed), pulls the model, and checks ffmpeg.
    """
    return StreamingResponse(_setup_stream(), media_type="text/event-stream")


async def _setup_stream() -> AsyncIterator[str]:
    """Yields SSE lines: data: {"step": str, "status": "ok"|"running"|"error", "msg": str}"""

    def sse(step: str, status: str, msg: str) -> str:
        payload = json.dumps({"step": step, "status": status, "msg": msg})
        return f"data: {payload}\n\n"

    os_name = platform.system()  # "Darwin" | "Windows" | "Linux"

    # ── Step 1: Ollama installed? ─────────────────────────────────────────────
    yield sse("ollama_install", "running", "Checking Ollama…")
    await asyncio.sleep(0)

    ollama_path = shutil.which("ollama")
    if ollama_path:
        yield sse("ollama_install", "ok", f"Ollama already installed ({ollama_path})")
    else:
        yield sse("ollama_install", "running", "Installing Ollama…")
        try:
            if os_name == "Darwin" or os_name == "Linux":
                proc = await asyncio.create_subprocess_shell(
                    "curl -fsSL https://ollama.com/install.sh | sh",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                async for line in proc.stdout:
                    yield sse("ollama_install", "running", line.decode(errors="ignore").rstrip())
                await proc.wait()
                if proc.returncode != 0:
                    yield sse("ollama_install", "error", "Ollama install failed. Visit https://ollama.com to install manually.")
                    return
            elif os_name == "Windows":
                import urllib.request, tempfile as _tf, os as _os
                yield sse("ollama_install", "running", "Downloading OllamaSetup.exe…")
                installer = _os.path.join(_tf.gettempdir(), "OllamaSetup.exe")
                urllib.request.urlretrieve("https://ollama.com/download/OllamaSetup.exe", installer)
                yield sse("ollama_install", "running", "Running installer (silent)…")
                proc = await asyncio.create_subprocess_exec(installer, "/S",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                await proc.wait()
            yield sse("ollama_install", "ok", "Ollama installed successfully")
        except Exception as exc:
            yield sse("ollama_install", "error", f"Could not install Ollama: {exc}")
            return

    # ── Step 2: Pull model ────────────────────────────────────────────────────
    _model = LLM_CONFIG["agent_model"]
    yield sse("model_pull", "running", f"Pulling model {_model} (this may take a few minutes)…")
    await asyncio.sleep(0)

    try:
        proc = await asyncio.create_subprocess_exec(
            "ollama", "pull", _model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            text = line.decode(errors="ignore").rstrip()
            if text:
                yield sse("model_pull", "running", text)
        await proc.wait()
        if proc.returncode == 0:
            yield sse("model_pull", "ok", f"{_model} ready")
        else:
            yield sse("model_pull", "error", f"ollama pull failed (exit {proc.returncode})")
            return
    except Exception as exc:
        yield sse("model_pull", "error", str(exc))
        return

    # ── Step 3: ffmpeg ────────────────────────────────────────────────────────
    yield sse("ffmpeg", "running", "Checking ffmpeg…")
    await asyncio.sleep(0)

    if shutil.which("ffmpeg"):
        yield sse("ffmpeg", "ok", "ffmpeg already installed")
    else:
        yield sse("ffmpeg", "running", "Installing ffmpeg…")
        try:
            if os_name == "Darwin":
                proc = await asyncio.create_subprocess_shell(
                    "brew install ffmpeg",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                async for line in proc.stdout:
                    yield sse("ffmpeg", "running", line.decode(errors="ignore").rstrip())
                await proc.wait()
                if proc.returncode == 0:
                    yield sse("ffmpeg", "ok", "ffmpeg installed via Homebrew")
                else:
                    yield sse("ffmpeg", "error", "Could not install ffmpeg. Run: brew install ffmpeg")
            elif os_name == "Windows":
                proc = await asyncio.create_subprocess_shell(
                    "winget install --id Gyan.FFmpeg -e --silent",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                await proc.wait()
                if proc.returncode == 0:
                    yield sse("ffmpeg", "ok", "ffmpeg installed via winget")
                else:
                    yield sse("ffmpeg", "error", "Could not install ffmpeg. Download from https://ffmpeg.org/download.html")
            else:
                proc = await asyncio.create_subprocess_shell(
                    "sudo apt-get install -y ffmpeg",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                await proc.wait()
                yield sse("ffmpeg", "ok" if proc.returncode == 0 else "error", "ffmpeg install done")
        except Exception as exc:
            yield sse("ffmpeg", "error", str(exc))

    # ── Step 4: Voicebox ──────────────────────────────────────────────────────
    yield sse("voicebox", "running", "Checking Voicebox…")
    await asyncio.sleep(0)

    voicebox_dir = Path(__file__).parent / "voicebox"

    if voicebox_dir.exists() and shutil.which("just"):
        yield sse("voicebox", "ok", "Voicebox already installed")
    else:
        # Need git
        if not shutil.which("git"):
            yield sse("voicebox", "error", "git not found — install Git and re-run setup")
        else:
            # Install Node.js if missing
            if not shutil.which("node"):
                yield sse("voicebox", "running", "Installing Node.js…")
                try:
                    if os_name == "Darwin":
                        proc = await asyncio.create_subprocess_shell(
                            "brew install node",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                        async for line in proc.stdout:
                            yield sse("voicebox", "running", line.decode(errors="ignore").rstrip())
                        await proc.wait()
                    elif os_name == "Windows":
                        proc = await asyncio.create_subprocess_shell(
                            "winget install --id OpenJS.NodeJS -e --silent",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                        await proc.wait()
                    else:
                        proc = await asyncio.create_subprocess_shell(
                            "sudo apt-get install -y nodejs npm",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                        await proc.wait()
                    yield sse("voicebox", "running", "Node.js installed")
                except Exception as exc:
                    yield sse("voicebox", "error", f"Could not install Node.js: {exc}")

            # Install just if missing
            if not shutil.which("just"):
                yield sse("voicebox", "running", "Installing 'just' task runner…")
                try:
                    if os_name == "Darwin":
                        proc = await asyncio.create_subprocess_shell(
                            "brew install just",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                        await proc.wait()
                    elif os_name == "Windows":
                        proc = await asyncio.create_subprocess_shell(
                            "winget install --id Casey.Just -e --silent",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                        await proc.wait()
                    else:
                        proc = await asyncio.create_subprocess_shell(
                            "curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                        await proc.wait()
                    yield sse("voicebox", "running", "'just' installed")
                except Exception as exc:
                    yield sse("voicebox", "error", f"Could not install just: {exc}")

            # Clone Voicebox
            if not voicebox_dir.exists():
                yield sse("voicebox", "running", "Cloning Voicebox repository…")
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "git", "clone", "https://github.com/jamiepine/voicebox",
                        str(voicebox_dir),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                    async for line in proc.stdout:
                        yield sse("voicebox", "running", line.decode(errors="ignore").rstrip())
                    await proc.wait()
                    if proc.returncode != 0:
                        yield sse("voicebox", "error", "git clone failed")
                except Exception as exc:
                    yield sse("voicebox", "error", f"Clone error: {exc}")

            # Run just setup
            if voicebox_dir.exists() and shutil.which("just"):
                yield sse("voicebox", "running", "Running 'just setup' (installing dependencies)…")
                try:
                    proc = await asyncio.create_subprocess_exec(
                        shutil.which("just"), "setup",
                        cwd=str(voicebox_dir),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                    async for line in proc.stdout:
                        text = line.decode(errors="ignore").rstrip()
                        if text:
                            yield sse("voicebox", "running", text)
                    await proc.wait()
                    if proc.returncode == 0:
                        yield sse("voicebox", "ok",
                            "Voicebox installed. It will start automatically next time you launch the server.")
                    else:
                        yield sse("voicebox", "error", "just setup failed — check voicebox/ directory")
                except Exception as exc:
                    yield sse("voicebox", "error", f"Setup error: {exc}")

    # ── Done ──────────────────────────────────────────────────────────────────
    yield sse("done", "ok", "Setup complete! Restart the server to apply all changes.")


# ── REST: file upload ──────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a video or audio file. Returns the saved path for use in chat messages."""
    suffix = Path(file.filename or "upload").suffix or ".mp4"
    dest   = TEMP_DIR / f"upload_{uuid.uuid4().hex}{suffix}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dest), "name": file.filename, "size": dest.stat().st_size}


# ── REST: output files ─────────────────────────────────────────────────────────

@app.get("/api/files")
async def list_files():
    """List all files in the output directory."""
    files = []
    for p in sorted(OUTPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            mime, _ = mimetypes.guess_type(str(p))
            files.append({
                "name":     p.name,
                "path":     str(p),
                "size":     p.stat().st_size,
                "mime":     mime or "application/octet-stream",
                "url":      f"/files/{p.name}",
                "modified": p.stat().st_mtime,
            })
    return files


@app.get("/files/{filename}")
async def serve_file(filename: str):
    """Serve a file from the output directory."""
    path = OUTPUT_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path))


# ── Static files (the UI) ──────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory="static", html=True), name="static")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
