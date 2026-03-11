"""Session persistence — save/restore conversation state via PostgreSQL."""

import json
import logging

import psycopg2
import psycopg2.extras

from config import CFG

log = logging.getLogger("session")


class SessionManager:
    """Manages conversation sessions in PostgreSQL.

    Sessions are keyed by (channel, user_id). One session per user per channel.
    On restart, existing sessions are automatically resumed from the database.
    """

    def __init__(self):
        self.conn = None
        self._enabled = False
        try:
            self.conn = psycopg2.connect(
                host=CFG.database.host,
                port=CFG.database.port,
                user=CFG.database.user,
                password=CFG.database.password,
                dbname=CFG.database.dbname,
            )
            self.conn.autocommit = True
            self._ensure_schema()
            self._enabled = True
            log.info("session manager ready (PostgreSQL)")
        except Exception as e:
            log.error("session manager init failed: %s", e)

    def _ensure_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
                    preview TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(channel, user_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_channel_user
                ON sessions(channel, user_id)
            """)

    @staticmethod
    def _make_id(channel: str, user_id: str) -> str:
        return f"{channel}:{user_id}"

    @staticmethod
    def _extract_preview(messages: list) -> str:
        for msg in messages:
            if msg.get("role") == "user":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "text" in block:
                        return block["text"][:80]
        return ""

    def get_or_create(self, channel: str, user_id: str) -> tuple[str, list]:
        """Return (session_id, history) — loads existing or creates new."""
        sid = self._make_id(channel, user_id)
        if not self._enabled:
            return sid, []
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT messages FROM sessions WHERE id = %s", (sid,))
            row = cur.fetchone()
            if row:
                log.info("resumed session %s", sid)
                return sid, row["messages"]
            # Create new
            cur.execute(
                "INSERT INTO sessions (id, channel, user_id) VALUES (%s, %s, %s)",
                (sid, channel, user_id),
            )
            log.info("new session %s", sid)
            return sid, []

    def save(self, session_id: str, messages: list):
        """Persist conversation history for a session."""
        if not self._enabled or not messages:
            return
        preview = self._extract_preview(messages)
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE sessions
                SET messages = %s, preview = %s, updated_at = now()
                WHERE id = %s
            """, (json.dumps(messages, default=str, ensure_ascii=False), preview, session_id))
        log.debug("saved session %s (%d messages)", session_id, len(messages))

    def load(self, session_id: str) -> list:
        """Load messages for a session by ID."""
        if not self._enabled:
            raise ValueError(f"Session store not available")
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT messages FROM sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Session '{session_id}' not found")
            log.info("loaded session: %s", session_id)
            return row["messages"]

    def list_sessions(self, limit: int = 20) -> str:
        """Return a formatted string listing recent sessions."""
        if not self._enabled:
            return "Session store not available."
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, channel, user_id, preview, updated_at
                FROM sessions ORDER BY updated_at DESC LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
        if not rows:
            return "No saved sessions."
        lines = []
        for r in rows:
            ts = r["updated_at"].strftime("%Y-%m-%d %H:%M") if r["updated_at"] else ""
            preview = (r["preview"] or "")[:60]
            lines.append(f"  {r['id']}  {ts}  {preview}")
        return "Sessions:\n" + "\n".join(lines)
