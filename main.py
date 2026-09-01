"""F2Media Stremio addon entry point.

Flow: Stremio stream request -> Cinemeta metadata -> F2MediaResolver
(discovery + validation + matching) -> content parser -> Stremio streams.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from httpclient.client import HttpClient, HttpClientConfig, HttpError
from httpclient.json_utils import parse_json_response
from parsers.f2medi_parser import parse_f2media_page
from resolvers import F2MediaResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("f2m.app")

app = FastAPI(
    title="F2Medi Stremio Add-on",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_http_client = HttpClient(HttpClientConfig.from_env())
_resolver = F2MediaResolver(http=_http_client)


def get_cinemeta_meta(item_type: str, imdb_id: str) -> dict | None:
    """Fetch item metadata (title/year) from Stremio's Cinemeta addon."""
    url = f"https://v3-cinemeta.strem.io/meta/{item_type}/{imdb_id}.json"
    try:
        response = _http_client.get(url, timeout=15.0)
    except HttpError as exc:
        logger.warning("[CINEMETA] request failed: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning("[CINEMETA] status=%d", response.status_code)
        return None

    payload = parse_json_response(response)
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    return meta if isinstance(meta, dict) else None


@app.get("/manifest.json")
def get_manifest():
    return {
        "id": "org.f2medi.stremio",
        "version": "3.0.0",
        "name": "F2Medi",
        "description": "جستجوی زنده فیلم و سریال‌های F2Medi برای Stremio",
        "types": ["movie", "series"],
        "resources": ["stream"],
        "idPrefixes": ["tt"],
        "catalogs": [],
    }


@app.get("/stream/{type}/{id}.json")
def get_streams(type: str, id: str):
    parts = id.split(":")
    imdb_id = parts[0]
    season = episode = None
    if type == "series" and len(parts) >= 3:
        season = parts[1]
        episode = parts[2]

    logger.info("[APP] stream request type=%s id=%s", type, imdb_id)

    meta = get_cinemeta_meta(type, imdb_id)
    if not meta or not meta.get("name"):
        logger.warning("[APP] no cinemeta metadata for %s", imdb_id)
        return {"streams": []}

    title = meta["name"]
    year_raw = meta.get("year")
    try:
        year = int(str(year_raw)[:4]) if year_raw else None
    except ValueError:
        year = None

    result = _resolver.resolve(
        title=title,
        item_type=type,
        imdb_id=imdb_id,
        year=year,
    )

    if not result.found or not result.html:
        logger.info("[APP] page not found for %s (%s)", title, imdb_id)
        return {"streams": []}

    try:
        page = parse_f2media_page(result.html, item_type=type, url=result.url or "")
    except Exception:
        logger.exception("[APP] parser crashed")
        return {"streams": []}

    stremio_streams = []
    for stream in page.streams:
        if type == "series":
            if season is not None and stream.season != season.zfill(2):
                continue
            if episode is not None and stream.episode != episode.zfill(2):
                continue

        url_out = stream.url
        if not url_out or url_out.lower().endswith(".mka"):
            continue

        language = (
            "🎤 دوبله فارسی"
            if stream.lang_type == "Dubbed"
            else "📝 زیرنویس چسبیده"
        )
        stremio_streams.append({
            "name": "F2Medi",
            "description": f"{stream.quality}\n{language}",
            "url": url_out,
            "behaviorHints": {
                "notWebReady": True,
                "bingeGroup": f"f2medi-{stream.quality}-{stream.lang_type or 'sub'}",
            },
        })

    logger.info("[APP] returning %d stream(s)", len(stremio_streams))
    if playing_hook:
        try:
            playing_hook(f"{title}" + (f" S{season}E{episode}" if season else ""))
        except Exception:
            pass
    return {"streams": stremio_streams}


playing_hook = None  # GUI sets this to a callable(str) to show what's playing


@app.get("/")
def health():
    return {"status": "ok", "addon": "F2Medi", "version": "3.0.0"}


ADDON_URL = "stremio://127.0.0.1:8081/manifest.json"


def _is_wsl() -> bool:
    """Detect if running inside WSL."""
    if "microsoft" in platform.release().lower():
        return True
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


STREMIO_EXE_NAMES = ["Stremio.exe", "stremio-shell-ng.exe", "stremio-runtime.exe"]


def _find_stremio_wsl() -> str | None:
    """Find Stremio.exe on Windows filesystem from WSL."""
    mnt_users = list(Path("/mnt/c/Users").glob("*"))
    windows_names = [
        "Program Files",
        "Program Files (x86)",
    ]
    localappdata_rel = "AppData/Local"

    exact_subpaths = [
        "Programs/Stremio",
        "Stremio",
    ]

    for user_dir in mnt_users:
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        local = user_dir / localappdata_rel
        for sub in exact_subpaths:
            for exe_name in STREMIO_EXE_NAMES:
                candidate = local / sub / exe_name
                if candidate.is_file():
                    return str(candidate)
        for wf in windows_names:
            for exe_name in STREMIO_EXE_NAMES:
                pf = Path(f"/mnt/c/{wf}")
                candidate = pf / "Stremio" / exe_name
                if candidate.is_file():
                    return str(candidate)

    # Glob fallback
    for mount in Path("/mnt").glob("*/Users/*/AppData/Local"):
        for exe_name in STREMIO_EXE_NAMES:
            for match in mount.glob(f"**/{exe_name}"):
                return str(match)

    return None


def _find_stremio_linux() -> str | None:
    """Find Stremio binary on Linux."""
    candidates = [
        "stremio",
        "/usr/bin/stremio",
        "/usr/local/bin/stremio",
        "/opt/Stremio/stremio",
        "/opt/stremio/stremio",
    ]
    # snap
    snap_stremio = Path("/snap/bin/stremio")
    if snap_stremio.exists():
        return str(snap_stremio)

    # .desktop file Exec line
    desktop_dirs = [
        Path.home() / ".local/share/applications",
        Path("/usr/share/applications"),
        Path("/var/lib/snapd/desktop/applications"),
    ]
    for d in desktop_dirs:
        for f in d.glob("*stremio*.desktop"):
            try:
                for line in f.read_text().splitlines():
                    if line.startswith("Exec="):
                        exe = line.split("=", 1)[1].split()[0]
                        if os.path.isfile(exe):
                            return exe
            except OSError:
                continue

    # flatpak
    try:
        result = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "stremio" in line.lower():
                return f"flatpak run {line.strip()}"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # PATH lookup
    for c in candidates:
        parts = c.split()
        try:
            subprocess.run(
                parts + ["--version"],
                capture_output=True, timeout=5,
            )
            return c
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None


def _find_stremio_windows() -> str | None:
    """Find Stremio.exe on Windows."""
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    pf = os.environ.get("PROGRAMFILES", "")
    pf86 = os.environ.get("PROGRAMFILES(X86)", "")
    userProfile = os.environ.get("USERPROFILE", "")

    exact_dirs = [
        os.path.join(local, "Programs", "Stremio"),
        os.path.join(local, "Stremio"),
        os.path.join(pf, "Stremio"),
        os.path.join(pf86, "Stremio"),
        os.path.join(appdata, "Local", "Programs", "Stremio"),
        os.path.join(userProfile, "AppData", "Local", "Programs", "Stremio"),
    ]
    for d in exact_dirs:
        for exe_name in STREMIO_EXE_NAMES:
            p = os.path.join(d, exe_name)
            if os.path.isfile(p):
                return p

    # Glob search in common root directories
    glob_roots = [local, pf, pf86, userProfile]
    for root in glob_roots:
        if not root:
            continue
        for exe_name in STREMIO_EXE_NAMES:
            for match in Path(root).glob(f"**/{exe_name}"):
                return str(match)

    return None


def launch_stremio() -> None:
    """Launch Stremio application."""
    system = platform.system()
    addon_msg = (
        "\n  To install the addon, open this URL in Stremio:\n"
        f"  {ADDON_URL}\n"
    )
    try:
        if system == "Linux":
            if _is_wsl():
                # Running in WSL — find and launch Windows Stremio.exe
                exe = _find_stremio_wsl()
                if not exe:
                    logger.warning(
                        "[LAUNCH] Stremio not found on Windows.%s"
                        "  Install: https://www.stremio.com/download",
                        addon_msg,
                    )
                    return
                # Launch via cmd.exe so the Windows GUI opens properly
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "", exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # Native Linux
                binary = _find_stremio_linux()
                if not binary:
                    logger.warning(
                        "[LAUNCH] Stremio not found.%s"
                        "  Install: https://www.stremio.com/download",
                        addon_msg,
                    )
                    return
                cmd = binary.split() if " " in binary else [binary]
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

        elif system == "Darwin":
            subprocess.Popen(
                ["open", "-a", "Stremio"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        elif system == "Windows":
            exe = _find_stremio_windows()
            if exe:
                subprocess.Popen(
                    [exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # fallback: try PATH
                try:
                    subprocess.Popen(
                        ["stremio"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except FileNotFoundError:
                    logger.warning(
                        "[LAUNCH] Stremio not found.%s"
                        "  Install: https://www.stremio.com/download",
                        addon_msg,
                    )
                    return
        else:
            logger.warning("[LAUNCH] unsupported OS: %s", system)
            return

        logger.info("[LAUNCH] Stremio launched successfully")
        logger.info("[LAUNCH] addon URL: %s", ADDON_URL)

    except FileNotFoundError:
        logger.warning(
            "[LAUNCH] Stremio not found.%s"
            "  Install: https://www.stremio.com/download",
            addon_msg,
        )


if __name__ == "__main__":
    def _run_server():
        uvicorn.run(app, host="127.0.0.1", port=8081)

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()
    time.sleep(1.5)
    launch_stremio()
    server_thread.join()
