"""
Premiere Pro WebSocket bridge – shared state between server.py and tools/premiere.py.

Flow:
  1. CEP panel connects to  ws://localhost:8000/ws/premiere  on startup
  2. Agent calls premiere_run_jsx(code)  →  _run_jsx()  →  send_jsx()
  3. Server sends {"id": "...", "jsx": "..."}  to the panel
  4. Panel runs  cs.evalScript(code, callback)  and replies {"id": "...", "result": "..."}
  5. Future resolves, tool returns the result to the agent
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

# Set by server.py once the event loop is running
_event_loop: Optional[asyncio.AbstractEventLoop] = None

# The single connected CEP panel WebSocket (only one Premiere instance at a time)
_panel_ws: Any = None  # FastAPI WebSocket

# Pending JSX requests: request_id -> Future
_pending: dict[str, asyncio.Future] = {}


# ── Called by server.py ───────────────────────────────────────────────────────

def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _event_loop
    _event_loop = loop


def set_panel(ws: Any) -> None:
    global _panel_ws
    _panel_ws = ws


def clear_panel() -> None:
    global _panel_ws
    _panel_ws = None
    # Fail any waiting requests
    for fut in _pending.values():
        if not fut.done():
            fut.set_exception(RuntimeError("Premiere Pro panel disconnected"))
    _pending.clear()


def is_connected() -> bool:
    return _panel_ws is not None


def resolve(req_id: str, result: str | None, error: str | None) -> None:
    """Called by the WS handler when the panel sends back a result."""
    fut = _pending.pop(req_id, None)
    if fut is None or fut.done():
        return
    if error:
        fut.set_exception(RuntimeError(f"Premiere ExtendScript error: {error}"))
    else:
        fut.set_result(result or "")


# ── Called by tools/premiere.py (from a thread) ───────────────────────────────

async def send_jsx(jsx_code: str, timeout: float = 60.0) -> str:
    """Coroutine: send JSX to the panel and await its response."""
    if _panel_ws is None:
        raise RuntimeError(
            "Premiere Pro is not connected.\n"
            "Make sure Premiere Pro is open and the AI Video Agent panel is visible "
            "(Window → Extensions → AI Video Agent)."
        )

    req_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _pending[req_id] = fut

    await _panel_ws.send_json({"id": req_id, "jsx": jsx_code})

    try:
        return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
    except asyncio.TimeoutError:
        _pending.pop(req_id, None)
        raise RuntimeError(f"Premiere Pro did not respond within {timeout}s")


def run_jsx_sync(jsx_code: str, timeout: float = 60.0) -> str:
    """
    Thread-safe wrapper around send_jsx.
    Called from the agent executor thread.
    """
    loop = _event_loop
    if loop is None or not loop.is_running():
        raise RuntimeError("Server event loop not available")
    future = asyncio.run_coroutine_threadsafe(
        send_jsx(jsx_code, timeout=timeout), loop
    )
    return future.result(timeout=timeout + 5)
