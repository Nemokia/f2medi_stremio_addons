#!/usr/bin/env python3
"""
Backend for F2Media Addon GUI.

Runs as a subprocess (called by gui.py). Exposes a small FastAPI control API:
- POST /api/connect   → starts the addon server (main.py) on port 8081
- POST /api/disconnect → stops the addon server
- GET  /api/playing    → returns current playing title
- GET  /api/logs       → streams addon server logs (SSE or simple JSON)

Works in both WSL and standalone (PyInstaller frozen EXE) modes.
"""
from __future__ import annotations
import threading
import time
import logging
import sys
from pathlib import Path

# ─── frozen / source detection ────────────────────────────────────────────
if getattr(sys, "frozen", False):
    # Running inside PyInstaller bundle — all source files are in _MEIPASS
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(PROJECT_ROOT))

import main as addon
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ─── logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("f2m.gui_backend")

# ─── shared state ─────────────────────────────────────────────────────────
state = {
    "server": None,          # uvicorn.Server instance for the addon
    "server_thread": None,   # thread running the addon server
    "playing": "",           # current playing title
    "log_lines": [],         # recent log lines from addon
    "log_lock": threading.Lock(),
}


def _on_playing(label: str) -> None:
    state["playing"] = label
    _add_log(f"▶ Playing: {label}")


addon.playing_hook = _on_playing


def _add_log(msg: str) -> None:
    with state["log_lock"]:
        state["log_lines"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(state["log_lines"]) > 500:
            state["log_lines"] = state["log_lines"][-500:]


# ─── FastAPI app (control API) ────────────────────────────────────────────
control = FastAPI(title="F2Media GUI Backend")

control.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@control.get("/")
def root():
    return {"service": "F2Media GUI Backend", "status": "running"}


@control.post("/api/connect")
def connect():
    """Start the addon server on port 8081."""
    if state["server"] and not state["server"].should_exit:
        return {"ok": True, "status": "already running"}

    state["playing"] = ""
    _add_log("Starting addon server on port 8081...")

    cfg = uvicorn.Config(
        addon.app,
        host="0.0.0.0",
        port=8081,
        log_level="warning",
        access_log=False,
    )
    srv = uvicorn.Server(cfg)
    state["server"] = srv

    def run_server():
        try:
            srv.run()
        except Exception as e:
            _add_log(f"Addon server error: {e}")
        finally:
            _add_log("Addon server stopped")

    t = threading.Thread(target=run_server, daemon=True)
    state["server_thread"] = t
    t.start()

    # Give it a moment to bind
    time.sleep(0.5)

    # Also launch Stremio (best effort)
    threading.Thread(target=_launch_stremio_safe, daemon=True).start()

    return {"ok": True, "status": "connected"}


@control.post("/api/disconnect")
def disconnect():
    """Stop the addon server."""
    _add_log("Stopping addon server...")
    if state["server"]:
        state["server"].should_exit = True
        state["server"] = None
    state["playing"] = ""
    _add_log("Addon server stopped")
    return {"ok": True, "status": "disconnected"}


@control.get("/api/playing")
def playing():
    return {"playing": state["playing"]}


@control.get("/api/logs")
def logs():
    """Return recent log lines as JSON."""
    with state["log_lock"]:
        return {"logs": state["log_lines"][-100:]}


@control.get("/api/logs/stream")
def logs_stream():
    """Server-Sent Events stream for live logs."""
    import asyncio

    async def event_generator():
        last_idx = 0
        while True:
            await asyncio.sleep(0.5)
            with state["log_lock"]:
                new_lines = state["log_lines"][last_idx:]
                last_idx = len(state["log_lines"])
            for line in new_lines:
                yield f"data: {line}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _launch_stremio_safe() -> None:
    time.sleep(1.5)
    try:
        addon.launch_stremio()
        _add_log("Stremio launch triggered")
    except Exception as e:
        _add_log(f"Stremio launch failed: {e}")


# ─── entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    _add_log("GUI Backend starting on port 9090")
    uvicorn.run(control, host="0.0.0.0", port=9090, log_level="warning", access_log=False)