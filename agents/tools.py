"""Base filesystem and shell tools."""

import subprocess
from pathlib import Path

from config import WORKDIR

BLOCKED_COMMANDS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
APPROVE_PATTERNS = ["rm ", "rmdir", "del ", "mv ", "move ", "git push", "git reset", "git checkout --", "git clean"]


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str, auto_approve: bool = False) -> str:
    if any(d in command for d in BLOCKED_COMMANDS):
        return "Error: Dangerous command blocked"
    if not auto_approve and any(p in command for p in APPROVE_PATTERNS):
        print(f"\n  ⚠ Command requires approval: {command}")
        answer = input("  Approve? [y/N] ").strip().lower()
        if answer != "y":
            return "Error: Command rejected by user"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True,
                           text=True, timeout=120, encoding="utf-8", errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        c = fp.read_text(encoding="utf-8")
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"
