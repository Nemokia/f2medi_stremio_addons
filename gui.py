#!/usr/bin/env python3
"""
F2Media Stremio Addon - Native Windows GUI (tkinter)

Default mode: double-click → GUI opens, service OFF.
User clicks Connect → starts addon server in WSL + launches Stremio.
User clicks Disconnect / closes window → kills addon server completely.
Logs stream into the GUI's log panel (no external CMD window needed).

Run from Windows:  python gui.py
Run from WSL (via WSLg):  ./venv/bin/python gui.py  (requires tkinter in venv)
"""
from __future__ import annotations
import threading
import subprocess
import sys
import queue
import time
import os
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext

# ─── paths & constants ────────────────────────────────────────────────────
ADDON_PORT = 8081


def _detect_wsl_project() -> str:
    """Auto-detect project dir and convert Windows path → WSL /mnt/... path."""
    win_dir = Path(__file__).resolve().parent  # e.g. D:\My projects\project\fardabin_stremio_addons
    drive = win_dir.drive[0].lower()            # "D"
    rest = str(win_dir)[len(win_dir.drive):]    # "\My projects\project\fardabin_stremio_addons"
    return f"/mnt/{drive}{rest}".replace("\\", "/")


WSL_PROJECT = _detect_wsl_project()
WSL_VENV_PYTHON = f"{WSL_PROJECT}/venv/bin/python"
WSL_GUI_ENTRY = f"{WSL_PROJECT}/gui_backend.py"

# ─── shared log queue ─────────────────────────────────────────────────────
log_queue: "queue.Queue[str]" = queue.Queue()


def log(msg: str) -> None:
    """Thread-safe log push."""
    log_queue.put(f"[{time.strftime('%H:%M:%S')}] {msg}")


# ─── backend control (runs in WSL) ────────────────────────────────────────
class AddonBackend:
    """Manages the addon server process inside WSL."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.monitor_thread: threading.Thread | None = None
        self.running = False

    def start(self) -> bool:
        if self.running:
            log("Backend already running")
            return True

        # Kill any leftover
        self.stop()

        # Launch the backend control server in WSL
        # It exposes /api/connect, /api/disconnect, /api/playing, /api/logs
        # Pass the command as a single quoted string to bash -lc
        # Use single quotes around the whole command to prevent Windows path mangling
        wsl_cmd = (
            f"cd '{WSL_PROJECT}' && "
            f"'{WSL_VENV_PYTHON}' '{WSL_GUI_ENTRY}'"
        )
        cmd = ["wsl.exe", "-e", "bash", "-lc", wsl_cmd]
        log(f"Starting backend: {' '.join(cmd)}")
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except Exception as e:
            log(f"Failed to start backend: {e}")
            return False

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_output, daemon=True)
        self.monitor_thread.start()

        # Wait a bit for server to come up, then call /api/connect
        time.sleep(1.5)
        self._call_connect()
        return True

    def _call_connect(self) -> None:
        import urllib.request
        import json
        try:
            req = urllib.request.Request("http://localhost:9090/api/connect", method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)
                log(f"Connect: {data.get('status', 'ok')}")
        except Exception as e:
            log(f"Connect failed: {e}")

    def stop(self) -> None:
        if not self.running and not self.proc:
            return
        log("Stopping backend...")
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:9090/api/disconnect", timeout=5)
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None
        self.running = False
        log("Backend stopped")

    def _monitor_output(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            log(f"[backend] {line.rstrip()}")
        self.running = False


# ─── Tkinter GUI ─────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("F2Media Addon")
        self.geometry("480x560")
        self.minsize(420, 500)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Dark theme colors
        self.bg = "#0f1629"
        self.panel = "#171f35"
        self.fg = "#eeeeee"
        self.accent = "#007DCC"
        self.accent_hover = "#0096e6"
        self.danger = "#B2054C"
        self.danger_hover = "#d40652"
        self.warn = "#FFB900"
        self.log_bg = "#0a0f1a"
        self.log_fg = "#a0c8e8"

        self.configure(bg=self.bg)
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._setup_styles()

        self.backend = AddonBackend()
        self.connected = False

        self._build_ui()
        self._poll_logs()

    def _setup_styles(self) -> None:
        self.style.configure("TFrame", background=self.bg)
        self.style.configure("TLabel", background=self.bg, foreground=self.fg, font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"), foreground="#D10056")
        self.style.configure("Status.TLabel", font=("Segoe UI", 11))
        self.style.configure("Connect.TButton", font=("Segoe UI", 11, "bold"), padding=10)
        self.style.configure("Disconnect.TButton", font=("Segoe UI", 11, "bold"), padding=10)
        self.style.map(
            "Connect.TButton",
            background=[("active", self.accent_hover), ("!disabled", self.accent)],
            foreground=[("!disabled", "#ffffff")],
        )
        self.style.map(
            "Disconnect.TButton",
            background=[("active", self.danger_hover), ("!disabled", self.danger)],
            foreground=[("!disabled", "#ffffff")],
        )

    def _build_ui(self) -> None:
        # Header
        header = ttk.Frame(self, padding=20)
        header.pack(fill="x")
        ttk.Label(header, text="🎬  F2Media Addon", style="Title.TLabel").pack(anchor="center")

        # Status
        self.status_var = tk.StringVar(value="● Disconnected")
        self.status_lbl = ttk.Label(self, textvariable=self.status_var, style="Status.TLabel", foreground=self.danger)
        self.status_lbl.pack(pady=(0, 16))

        # Now playing
        self.playing_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.playing_var, style="Status.TLabel", foreground=self.warn, wraplength=420).pack(pady=(0, 20))

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=10)
        self.connect_btn = ttk.Button(
            btn_frame, text="● Connect", style="Connect.TButton",
            command=self.on_connect, width=16
        )
        self.connect_btn.pack(side="left", padx=8)
        self.disconnect_btn = ttk.Button(
            btn_frame, text="■ Disconnect", style="Disconnect.TButton",
            command=self.on_disconnect, width=16, state="disabled"
        )
        self.disconnect_btn.pack(side="left", padx=8)

        # Logs
        log_frame = ttk.Frame(self, padding=(20, 10, 20, 20))
        log_frame.pack(fill="both", expand=True)
        ttk.Label(log_frame, text="Logs", style="Status.TLabel").pack(anchor="w", pady=(0, 6))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            bg=self.log_bg,
            fg=self.log_fg,
            insertbackground=self.fg,
            font=("Consolas", 9),
            relief="flat",
            borderwidth=0,
            state="disabled",
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("error", foreground="#ff6b6b")
        self.log_text.tag_config("warn", foreground="#ffb900")
        self.log_text.tag_config("info", foreground="#7dd3fc")
        self.log_text.tag_config("success", foreground="#4ade80")

        # Initial log
        self._append_log("F2Media Addon GUI ready. Click Connect to start.", "info")

    def _append_log(self, msg: str, tag: str = "") -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_logs(self) -> None:
        try:
            while True:
                msg = log_queue.get_nowait()
                tag = ""
                if "error" in msg.lower() or "fail" in msg.lower() or "exception" in msg.lower():
                    tag = "error"
                elif "warn" in msg.lower():
                    tag = "warn"
                elif "connect" in msg.lower() and "connected" in msg.lower():
                    tag = "success"
                elif "stop" in msg.lower() or "disconnect" in msg.lower():
                    tag = "warn"
                self._append_log(msg, tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    def on_connect(self) -> None:
        self.connect_btn.configure(state="disabled")
        self._append_log("Starting addon server in WSL...", "info")
        threading.Thread(target=self._do_connect, daemon=True).start()

    def _do_connect(self) -> None:
        ok = self.backend.start()
        self.after(0, lambda: self._connect_done(ok))

    def _connect_done(self, ok: bool) -> None:
        if ok:
            self.connected = True
            self.status_var.set("● Connected")
            self.status_lbl.configure(foreground="#007DCC")
            self.connect_btn.configure(state="disabled")
            self.disconnect_btn.configure(state="normal")
            self._append_log("Addon server running on port 8081", "success")
            self._append_log("Launching Stremio...", "info")
            # Stremio launch is handled by backend
        else:
            self.connect_btn.configure(state="normal")
            self._append_log("Failed to start backend", "error")

    def on_disconnect(self) -> None:
        self.disconnect_btn.configure(state="disabled")
        self._append_log("Disconnecting...", "warn")
        threading.Thread(target=self._do_disconnect, daemon=True).start()

    def _do_disconnect(self) -> None:
        self.backend.stop()
        self.after(0, self._disconnect_done)

    def _disconnect_done(self) -> None:
        self.connected = False
        self.status_var.set("● Disconnected")
        self.status_lbl.configure(foreground=self.danger)
        self.playing_var.set("")
        self.connect_btn.configure(state="normal")
        self.disconnect_btn.configure(state="disabled")
        self._append_log("Disconnected", "warn")

    def on_close(self) -> None:
        if self.connected:
            self._append_log("Window closed — stopping backend...", "warn")
            self.backend.stop()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()