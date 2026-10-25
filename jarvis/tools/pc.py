"""Control the Windows PC: apps, URLs, media keys, system stats, shell commands."""
import ctypes
import os
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import psutil

from ..config import WORKSPACE
from . import clip, string, tool

NO_WINDOW = 0x08000000

ALIASES = {
    "notepad": "notepad", "calculator": "calc", "calc": "calc", "paint": "mspaint",
    "explorer": "explorer", "file explorer": "explorer", "files": "explorer",
    "terminal": "wt", "powershell": "powershell", "command prompt": "cmd", "cmd": "cmd",
    "task manager": "taskmgr", "settings": "ms-settings:", "edge": "msedge", "chrome": "chrome",
    "vscode": "code", "vs code": "code", "visual studio code": "code", "spotify": "spotify:",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt", "outlook": "outlook",
    "snipping tool": "snippingtool", "camera": "microsoft.windows.camera:", "store": "ms-windows-store:",
}

START_MENUS = [
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
    Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
]


def _find_shortcut(name: str) -> Path | None:
    name = name.lower()
    best = None
    for root in START_MENUS:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if stem == name:
                return lnk
            if name in stem and "uninstall" not in stem and (best is None or len(stem) < len(best.stem)):
                best = lnk
    return best


@tool("Open/launch an application by name, e.g. 'notepad', 'spotify', 'chrome', 'discord'.",
      {"name": string("Application name")})
def open_app(name: str) -> str:
    key = name.strip().lower()
    if key in ALIASES:
        target = ALIASES[key]
    elif lnk := _find_shortcut(key):
        os.startfile(lnk)
        return f"Launched {lnk.stem}"
    else:
        target = key
    subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=NO_WINDOW)
    return f"Launched {name}"


@tool("Open a website in the default browser.", {"url": string("Full URL or domain")})
def open_url(url: str) -> str:
    if "://" not in url:
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}"


MEDIA = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "mute": 0xAD,
         "volume_up": 0xAF, "volume_down": 0xAE}


@tool("Control media playback and system volume.",
      {"action": {"type": "string", "enum": list(MEDIA),
                  "description": "play_pause, next, previous, mute, volume_up, volume_down"}})
def media_control(action: str) -> str:
    vk = MEDIA.get(action)
    if vk is None:
        return f"Unknown action {action}"
    for _ in range(5 if action.startswith("volume") else 1):  # each volume press is only 2%
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    return f"Done: {action}"


@tool("Lock the computer screen.")
def lock_screen() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Screen locked"


@tool("Get the current local date and time.")
def get_time() -> str:
    return datetime.now().strftime("%A %d %B %Y, %I:%M %p")


def stats() -> dict:
    vm = psutil.virtual_memory()
    bat = psutil.sensors_battery()
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": vm.percent,
        "ram_used_gb": round(vm.used / 2**30, 1),
        "ram_total_gb": round(vm.total / 2**30, 1),
        "disk": psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent,
        "battery": None if bat is None else round(bat.percent),
        "plugged": None if bat is None else bat.power_plugged,
        "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
    }


@tool("Get system status: CPU, memory, disk, battery, uptime and the top processes by memory.")
def system_status() -> str:
    s = stats()
    procs = sorted(psutil.process_iter(["name", "memory_info"]),
                   key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)[:5]
    top = ", ".join(f"{p.info['name']} {p.info['memory_info'].rss / 2**20:.0f}MB" for p in procs)
    bat = "no battery" if s["battery"] is None else f"battery {s['battery']}% ({'charging' if s['plugged'] else 'on battery'})"
    return (f"CPU {s['cpu']}%, RAM {s['ram']}% ({s['ram_used_gb']}/{s['ram_total_gb']} GB), "
            f"disk {s['disk']}% full, {bat}, uptime {s['uptime_h']} h. Top memory: {top}")


@tool("Run a PowerShell command on this PC and return its output. Use for anything the other tools "
      "can't do (installing, deleting, git, running scripts, querying Windows). The user must approve it.",
      {"command": string("PowerShell command")},
      confirm=lambda a: f"Run PowerShell: {a.get('command', '')}")
def run_command(command: str) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                           capture_output=True, text=True, timeout=120, cwd=WORKSPACE,
                           creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "Command timed out after 120 s"
    out = (r.stdout + ("\n[stderr]\n" + r.stderr if r.stderr.strip() else "")).strip()
    return clip(f"exit {r.returncode}\n{out or '(no output)'}")
