"""Session persistence - save/restore conversation state."""

import json
import logging
import time
from pathlib import Path

from config import SESSIONS_DIR

log = logging.getLogger("session")


class SessionManager:
    def __init__(self):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.current_id = None

    def new_session(self) -> str:
        self.current_id = f"s_{int(time.time())}"
        log.info("new session: %s", self.current_id)
        return self.current_id

    def save(self, messages: list):
        if not self.current_id or not messages:
            return
        path = SESSIONS_DIR / f"{self.current_id}.json"
        preview = ""
        for msg in messages:
            if msg["role"] == "user":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "text" in block:
                        preview = block["text"][:80]
                        break
                if preview:
                    break
        data = {
            "id": self.current_id,
            "updated": time.time(),
            "preview": preview,
            "messages": messages,
        }
        path.write_text(
            json.dumps(data, default=str, ensure_ascii=False), encoding="utf-8"
        )
        log.debug("saved session %s (%d messages)", self.current_id, len(messages))

    def load(self, session_id: str) -> list:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            raise ValueError(f"Session '{session_id}' not found")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.current_id = session_id
        log.info("resumed session: %s", session_id)
        return data["messages"]

    def list_sessions(self) -> str:
        sessions = []
        for f in sorted(
            SESSIONS_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(data.get("updated", 0))
                )
                preview = data.get("preview", "")[:60]
                sessions.append(f"  {data['id']}  {ts}  {preview}")
            except Exception:
                continue
        if not sessions:
            return "No saved sessions."
        return "Sessions:\n" + "\n".join(sessions[:20])
