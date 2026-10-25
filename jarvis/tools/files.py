"""Create, read and open files. Anything inside the workspace folder is fair game; writing anywhere
else needs the user's OK."""
import os
from pathlib import Path

from ..config import WORKSPACE
from . import clip, string, tool


def resolve(path: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(path.strip().strip('"'))))
    return (p if p.is_absolute() else WORKSPACE / p).resolve()


def in_workspace(p: Path) -> bool:
    return p == WORKSPACE or WORKSPACE in p.parents


def _write_confirm(args: dict) -> str | None:
    p = resolve(args.get("path", ""))
    if in_workspace(p):
        return None
    return f"{'Overwrite' if p.exists() else 'Create'} file outside the workspace: {p}"


@tool("Create or overwrite a text file (code, notes, scripts, etc.). Relative paths go in the "
      "JARVIS workspace folder. Parent folders are created automatically.",
      {"path": string("File path, e.g. 'snake_game.py' or 'notes/todo.md'"),
       "content": string("Full file contents")},
      confirm=_write_confirm)
def write_file(path: str, content: str) -> str:
    p = resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {p}"


@tool("Read a text file.", {"path": string("File path; relative paths are in the workspace")})
def read_file(path: str) -> str:
    p = resolve(path)
    if not p.is_file():
        return f"No such file: {p}"
    return clip(p.read_text(encoding="utf-8", errors="replace"), 8000)


@tool("List files and folders in a directory.",
      {"path": string("Directory; defaults to the workspace")}, required=[])
def list_files(path: str = ".") -> str:
    p = resolve(path)
    if not p.is_dir():
        return f"Not a directory: {p}"
    items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:100]
    lines = [f"{'[dir] ' if i.is_dir() else ''}{i.name}" for i in items]
    return f"{p}:\n" + ("\n".join(lines) or "(empty)")


@tool("Open a file or folder with its default Windows program (e.g. open the workspace in Explorer).",
      {"path": string("File or folder path; '.' is the workspace")})
def open_path(path: str) -> str:
    p = resolve(path)
    if not p.exists():
        return f"Not found: {p}"
    os.startfile(p)
    return f"Opened {p}"
