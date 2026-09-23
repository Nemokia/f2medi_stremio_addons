#!/usr/bin/env python3
"""
F2Media Stremio Addon — Standalone entry point for PyInstaller.

When built as F2Media.exe, this script handles two modes:
  - No args (or non-backend args) → launches the tkinter GUI
  - --backend → runs the backend control server (gui_backend.py logic)

This allows a single EXE to serve both roles: the GUI spawns a second
instance of itself with --backend to run the addon server.
"""
from __future__ import annotations
import sys
import os
from pathlib import Path


def _setup_paths() -> None:
    """Ensure the project root is on sys.path (works in both frozen and source modes)."""
    if getattr(sys, "frozen", False):
        # Running inside PyInstaller bundle
        project_root = Path(sys._MEIPASS)
    else:
        project_root = Path(__file__).resolve().parent
    # Add project root so that 'import main', 'import gui_backend', etc. work
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    # Change working directory to project root (needed for relative path resolution)
    os.chdir(str(project_root))


def _clear_proxy_env() -> None:
    """Clear proxy env vars that cause SOCKS errors when PySocks is not installed."""
    for var in (
        "HTTP_PROXY", "http_proxy",
        "HTTPS_PROXY", "https_proxy",
        "ALL_PROXY", "all_proxy",
        "SOCKS_PROXY", "socks_proxy",
    ):
        os.environ.pop(var, None)


def main() -> None:
    _setup_paths()
    _clear_proxy_env()

    if "--backend" in sys.argv:
        # ─── Backend mode: run the control server ───────────────────────
        # Import and run gui_backend's main block
        import gui_backend  # noqa: E402 — imports happen after path setup
        import uvicorn  # noqa: E402

        gui_backend._add_log("GUI Backend (standalone) starting on port 9090")
        uvicorn.run(
            gui_backend.control,
            host="0.0.0.0",
            port=9090,
            log_level="warning",
            access_log=False,
        )
    else:
        # ─── GUI mode: launch the tkinter interface ─────────────────────
        import gui  # noqa: E402
        gui.main()


if __name__ == "__main__":
    main()
