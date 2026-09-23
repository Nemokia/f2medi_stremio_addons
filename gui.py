#!/usr/bin/env python3
"""
F2Media Stremio Addon - Native Windows GUI (tkinter)

Default mode: double-click -> GUI opens, service OFF.
User clicks Connect -> starts addon server locally or in WSL + launches Stremio.
User clicks Disconnect / closes window -> kills addon server completely.
Logs stream into the GUI's log panel (no external CMD window needed).

Runs in two modes:
  1. Standalone EXE (PyInstaller frozen): launches F2Media.exe --backend locally
  2. Source / WSL: launches gui_backend.py via WSL

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
from tkinter import scrolledtext

# ─── frozen / source detection ────────────────────────────────────────────
FROZEN = getattr(sys, "frozen", False)
ADDON_PORT = 8081


def _detect_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _detect_wsl_project() -> str:
    win_dir = _detect_project_root()
    if not win_dir.drive:
        return str(win_dir)
    drive = win_dir.drive[0].lower()
    rest = str(win_dir)[len(win_dir.drive):]
    return f"/mnt/{drive}{rest}".replace("\\", "/")


PROJECT_ROOT = _detect_project_root()
WSL_PROJECT = _detect_wsl_project()
WSL_VENV_PYTHON = f"{WSL_PROJECT}/venv/bin/python"
WSL_GUI_ENTRY = f"{WSL_PROJECT}/gui_backend.py"

# ─── shared log queue ─────────────────────────────────────────────────────
log_queue: "queue.Queue[str]" = queue.Queue()


def log(msg: str) -> None:
    log_queue.put(f"[{time.strftime('%H:%M:%S')}] {msg}")


# ─── backend control ──────────────────────────────────────────────────────
class AddonBackend:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.monitor_thread: threading.Thread | None = None
        self.running = False

    def start(self) -> bool:
        if self.running:
            log("Backend already running")
            return True
        self.stop()

        if FROZEN:
            cmd = [sys.executable, "--backend"]
            log(f"Starting backend (standalone): {sys.executable} --backend")
        else:
            wsl_cmd = f"cd '{WSL_PROJECT}' && '{WSL_VENV_PYTHON}' '{WSL_GUI_ENTRY}'"
            cmd = ["wsl.exe", "-e", "bash", "-lc", wsl_cmd]
            log(f"Starting backend (WSL): {' '.join(cmd)}")

        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", bufsize=1,
            )
        except Exception as e:
            log(f"Failed to start backend: {e}")
            return False

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_output, daemon=True)
        self.monitor_thread.start()
        time.sleep(1.5)
        self._call_connect()
        return True

    def _call_connect(self) -> None:
        import urllib.request, json
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
        self.geometry("500x620")
        self.minsize(440, 560)
        self.configure(bg="#0f1629")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.backend = AddonBackend()
        self.connected = False

        self._build_ui()
        self._poll_logs()

    def _build_ui(self) -> None:
        # ── Header ──────────────────────────────────────────────────
        header = tk.Frame(self, bg="#0f1629")
        header.pack(fill="x", pady=(18, 0))
        tk.Label(header, text="\U0001f3ac  F2Media Addon", bg="#0f1629",
                 fg="#D10056", font=("Segoe UI", 18, "bold")).pack()

        # ── Status label ────────────────────────────────────────────
        self.status_var = tk.StringVar(value="\u25cf Disconnected")
        self.status_lbl = tk.Label(self, textvariable=self.status_var,
                                   bg="#0f1629", fg="#B2054C",
                                   font=("Segoe UI", 12, "bold"))
        self.status_lbl.pack(pady=(10, 2))

        # ── Info box (IP URL + now-playing) above buttons ───────────
        self.info_frame = tk.Frame(self, bg="#171f35", bd=0, highlightthickness=1,
                                   highlightbackground="#2a3555")
        self.info_frame.pack(padx=28, pady=(4, 8), fill="x")

        self.url_var = tk.StringVar(value="")
        self.url_lbl = tk.Label(self.info_frame, textvariable=self.url_var,
                                bg="#171f35", fg="#4ade80",
                                font=("Consolas", 10), cursor="hand2",
                                anchor="w", padx=10, pady=6)
        self.url_lbl.pack(fill="x")
        self.url_lbl.bind("<Button-1>", self._copy_url)

        self.playing_var = tk.StringVar(value="")
        self.playing_lbl = tk.Label(self.info_frame, textvariable=self.playing_var,
                                    bg="#171f35", fg="#FFB900",
                                    font=("Segoe UI", 10), anchor="w",
                                    padx=10, wraplength=420)
        self.playing_lbl.pack(fill="x", pady=(0, 6))

        # ── Buttons (plain tk.Button with colors) ───────────────────
        btn_frame = tk.Frame(self, bg="#0f1629")
        btn_frame.pack(pady=8)

        self.connect_btn = tk.Button(
            btn_frame, text="\u25cf Connect",
            bg="#007DCC", fg="white", activebackground="#0096e6", activeforeground="white",
            font=("Segoe UI", 11, "bold"), relief="flat", padx=20, pady=6,
            cursor="hand2", command=self.on_connect,
        )
        self.connect_btn.pack(side="left", padx=10)

        self.disconnect_btn = tk.Button(
            btn_frame, text="\u25a0 Disconnect",
            bg="#B2054C", fg="white", activebackground="#d40652", activeforeground="white",
            font=("Segoe UI", 11, "bold"), relief="flat", padx=20, pady=6,
            cursor="hand2", command=self.on_disconnect,
        )
        self.disconnect_btn.pack(side="left", padx=10)
        self.disconnect_btn.configure(state="disabled", bg="#3a3a4a", fg="#888888",
                                      activebackground="#3a3a4a", activeforeground="#888888")

        # ── Logs ────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg="#0f1629")
        log_frame.pack(fill="both", expand=True, padx=20, pady=(6, 16))
        tk.Label(log_frame, text="Logs", bg="#0f1629", fg="#a0c8e8",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 4))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=12, bg="#0a0f1a", fg="#a0c8e8",
            insertbackground="#eeeeee", font=("Consolas", 9),
            relief="flat", borderwidth=0, state="disabled", wrap="word",
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("error", foreground="#ff6b6b")
        self.log_text.tag_config("warn", foreground="#ffb900")
        self.log_text.tag_config("info", foreground="#7dd3fc")
        self.log_text.tag_config("success", foreground="#4ade80")

        mode = "standalone" if FROZEN else "source (WSL)"
        self._append_log(f"F2Media Addon GUI ready ({mode}). Click Connect to start.", "info")

    # ── URL copy ────────────────────────────────────────────────────
    def _copy_url(self, _event=None) -> None:
        url = self.url_var.get().replace("  \U0001f517  ", "").replace("  (click to copy)", "").strip()
        if url:
            self.clipboard_clear()
            self.clipboard_append(url)
            old = self.url_var.get()
            self.url_var.set("  Copied!")
            self.after(1200, lambda: self.url_var.set(old))

    # ── Log helpers ─────────────────────────────────────────────────
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

    # ── Connect / Disconnect ────────────────────────────────────────
    def on_connect(self) -> None:
        self.connect_btn.configure(state="disabled")
        mode = "locally" if FROZEN else "in WSL"
        self._append_log(f"Starting addon server {mode}...", "info")
        threading.Thread(target=self._do_connect, daemon=True).start()

    def _do_connect(self) -> None:
        ok = self.backend.start()
        self.after(0, lambda: self._connect_done(ok))

    def _connect_done(self, ok: bool) -> None:
        if ok:
            self.connected = True
            self.status_var.set("\u25cf Connected")
            self.status_lbl.configure(foreground="#007DCC")
            self.connect_btn.configure(state="disabled", bg="#3a3a4a", fg="#888888",
                                       activebackground="#3a3a4a", activeforeground="#888888")
            self.disconnect_btn.configure(state="normal", bg="#B2054C", fg="white",
                                          activebackground="#d40652", activeforeground="white")
            self._append_log("Addon server running on port 8081", "success")
            self._append_log("Launching Stremio...", "info")
            local_ip = _get_local_ip()
            if local_ip != "127.0.0.1":
                url = f"http://{local_ip}:8081/manifest.json"
                self.url_var.set(f"  \U0001f517  {url}  (click to copy)")
            else:
                self.url_var.set("")
        else:
            self.connect_btn.configure(state="normal", bg="#007DCC", fg="white",
                                       activebackground="#0096e6", activeforeground="white")
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
        self.status_var.set("\u25cf Disconnected")
        self.status_lbl.configure(foreground="#B2054C")
        self.playing_var.set("")
        self.url_var.set("")
        self.connect_btn.configure(state="normal", bg="#007DCC", fg="white",
                                   activebackground="#0096e6", activeforeground="white")
        self.disconnect_btn.configure(state="disabled", bg="#3a3a4a", fg="#888888",
                                      activebackground="#3a3a4a", activeforeground="#888888")
        self._append_log("Disconnected", "warn")

    def on_close(self) -> None:
        if self.connected:
            self._append_log("Window closed - stopping backend...", "warn")
            self.backend.stop()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
