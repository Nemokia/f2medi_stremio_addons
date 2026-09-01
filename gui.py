"""Minimal control panel for F2Media Stremio addon.

Run:  ./venv/bin/python gui.py
Opens a browser tab with Connect/Disconnect buttons and now-playing title.
Addon API then serves on 0.0.0.0:8081 (Stremio connects to it).
"""
import threading
import time
import subprocess
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

import main as addon


CONTROL_PORT = 9090
ADDON_PORT = 8081

control = FastAPI()
state = {"server": None, "playing": ""}


def _on_playing(label: str):
    state["playing"] = label


addon.playing_hook = _on_playing


def _open_browser(url: str):
    # WSL: open in Windows default browser; fallback to webbrowser
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        import webbrowser
        webbrowser.open(url)


PAGE = """<!DOCTYPE html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>F2Media</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#0f1629;color:#eee}
.box{text-align:center;width:380px;padding:30px 20px;border-radius:16px;background:#171f35;box-shadow:0 4px 30px rgba(0,125,204,.15)}
h1{color:#D10056;font-size:1.5em;margin:0 0 8px}
#st{margin:14px 0;font-size:1.1em}
.on{color:#007DCC}.off{color:#B2054C}
button{padding:12px 30px;margin:5px;border:0;border-radius:8px;font-size:1em;font-weight:700;cursor:pointer;transition:filter .15s}
button:hover:not(:disabled){filter:brightness(1.15)}
#c{background:#007DCC;color:#fff}#d{background:#B2054C;color:#fff}
button:disabled{background:#232b42;color:#555;cursor:default}
#p{margin-top:18px;color:#FFB900;min-height:1.5em;font-size:1.05em}
</style></head><body><div class="box">
<h1>🎬 F2Media Addon</h1>
<div id="st" class="off"> ● disconnected</div>
<button id="c" onclick="f('connect')">● Connect</button>
<button id="d" onclick="f('disconnect')" disabled>■ Disconnect</button>
<div id="p"></div>
</div>
<script>
let t;
async function f(a){
  const r=await (await fetch('/api/'+a)).json();
  const on=a==='connect';
  st.textContent=on?'● connected':'● disconnected';
  st.className=on?'on':'off';
  c.disabled=on; d.disabled=!on;
  if(on){p.textContent='⏳ starting…'; start();}
  else{p.textContent=''; stop();}
}
function start(){stop();t=setInterval(async()=>{
  const d=await (await fetch('/api/playing')).json();
  p.textContent=d.playing?'▶ '+d.playing:'';
},1500);}
function stop(){if(t)clearInterval(t)}
</script></body></html>"""


@control.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@control.get("/api/connect")
def connect():
    if state["server"] and not state["server"].should_exit:
        return {"ok": True, "status": "already running"}
    state["playing"] = ""
    cfg = uvicorn.Config(addon.app, host="0.0.0.0", port=ADDON_PORT, log_level="warning")
    srv = uvicorn.Server(cfg)
    state["server"] = srv
    threading.Thread(target=srv.run, daemon=True).start()
    threading.Thread(target=_launch_stremio_later, daemon=True).start()
    return {"ok": True, "status": "connected"}


@control.get("/api/disconnect")
def disconnect():
    if state["server"]:
        state["server"].should_exit = True
        state["server"] = None
    state["playing"] = ""
    return {"ok": True, "status": "disconnected"}


@control.get("/api/playing")
def playing():
    return {"playing": state["playing"]}


def _launch_stremio_later():
    time.sleep(1.5)
    try:
        addon.launch_stremio()
    except Exception:
        pass


if __name__ == "__main__":
    _open_browser(f"http://localhost:{CONTROL_PORT}/")
    uvicorn.run(control, host="0.0.0.0", port=CONTROL_PORT, log_level="warning")
