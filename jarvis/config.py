"""All settings live here. Override any of them with an environment variable (or a .env-style
line in start-jarvis.ps1) instead of editing code."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUD_DIR = ROOT / "hud"
DATA_DIR = ROOT / "data"
WORKSPACE = Path(os.getenv("JARVIS_WORKSPACE", ROOT / "workspace")).resolve()

# Brain. qwen2.5:3b is quick on a laptop CPU; qwen2.5:7b is noticeably smarter but ~2x slower.
MODEL = os.getenv("JARVIS_MODEL", "qwen2.5:3b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
NUM_CTX = int(os.getenv("JARVIS_NUM_CTX", "8192"))

# Personality / voice.
USER_TITLE = os.getenv("JARVIS_USER_TITLE", "sir")
VOICE = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural")  # any edge-tts voice; `edge-tts --list-voices`
VOICE_RATE = os.getenv("JARVIS_VOICE_RATE", "+8%")

# Web / info defaults.
CITY = os.getenv("JARVIS_CITY", "")  # empty = locate by IP
NEWS_REGION = os.getenv("JARVIS_NEWS_REGION", "US:en")  # Google News country:language, e.g. AU:en, GB:en

HOST = os.getenv("JARVIS_HOST", "127.0.0.1")
PORT = int(os.getenv("JARVIS_PORT", "8765"))

DATA_DIR.mkdir(exist_ok=True)
WORKSPACE.mkdir(parents=True, exist_ok=True)
