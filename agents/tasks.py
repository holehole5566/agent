"""Persistent task manager backed by PostgreSQL."""

import json
import logging
import threading

import psycopg2
import psycopg2.extras

from config import CFG

log = logging.getLogger("tasks")


class TaskManager:
    """Manages tasks in PostgreSQL.

    Same API as the original file-based TaskManager, but backed by a
    'tasks' table for persistence across restarts.
    """

    def __init__(self):
        self.conn = None
        self._enabled = False
        self._lock = threading.Lock()
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
            log.info("task manager ready (PostgreSQL)")
        except Exception as e:
            log.error("task manager init failed: %s", e)

    def _ensure_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    subject TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    owner TEXT,
                    blocked_by INTEGER[] DEFAULT '{}',
                    blocks INTEGER[] DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)

    def _row_to_dict(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "subject": row["subject"],
            "description": row["description"] or "",
            "status": row["status"],
            "owner": row["owner"],
            "blockedBy": list(row["blocked_by"] or []),
            "blocks": list(row["blocks"] or []),
        }

    def _load(self, tid: int) -> dict:
        if not self._enabled:
            raise ValueError(f"Task store not available")
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM tasks WHERE id = %s", (tid,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Task {tid} not found")
            return self._row_to_dict(row)

    def create(self, subject: str, description: str = "") -> str:
        if not self._enabled:
            return json.dumps({"error": "Task store not available"})
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO tasks (subject, description) VALUES (%s, %s) RETURNING *",
                (subject, description),
            )
            row = cur.fetchone()
        task = self._row_to_dict(row)
        log.info("created task #%d: %s", task["id"], subject)
        return json.dumps(task, indent=2)

    def get(self, tid: int) -> str:
        return json.dumps(self._load(tid), indent=2)

    def update(self, tid: int, status: str = None,
               add_blocked_by: list = None, add_blocks: list = None) -> str:
        task = self._load(tid)
        with self.conn.cursor() as cur:
            if status:
                if status == "deleted":
                    cur.execute("DELETE FROM tasks WHERE id = %s", (tid,))
                    if status == "completed":
                        # Unblock dependent tasks
                        cur.execute(
                            "UPDATE tasks SET blocked_by = array_remove(blocked_by, %s), updated_at = now() WHERE %s = ANY(blocked_by)",
                            (tid, tid),
                        )
                    log.info("deleted task #%d", tid)
                    return f"Task {tid} deleted"
                cur.execute(
                    "UPDATE tasks SET status = %s, updated_at = now() WHERE id = %s",
                    (status, tid),
                )
                if status == "completed":
                    cur.execute(
                        "UPDATE tasks SET blocked_by = array_remove(blocked_by, %s), updated_at = now() WHERE %s = ANY(blocked_by)",
                        (tid, tid),
                    )
            if add_blocked_by:
                for b in add_blocked_by:
                    cur.execute(
                        "UPDATE tasks SET blocked_by = array_append(blocked_by, %s), updated_at = now() WHERE id = %s AND NOT (%s = ANY(blocked_by))",
                        (b, tid, b),
                    )
            if add_blocks:
                for b in add_blocks:
                    cur.execute(
                        "UPDATE tasks SET blocks = array_append(blocks, %s), updated_at = now() WHERE id = %s AND NOT (%s = ANY(blocks))",
                        (b, tid, b),
                    )
        return json.dumps(self._load(tid), indent=2)

    def list_all(self) -> str:
        if not self._enabled:
            return "Task store not available."
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM tasks ORDER BY id")
            rows = cur.fetchall()
        if not rows:
            return "No tasks."
        lines = []
        for row in rows:
            t = self._row_to_dict(row)
            m = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{m} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        with self._lock:
            try:
                task = self._load(tid)
            except ValueError:
                return f"Error: Task {tid} not found"
            if task.get("owner"):
                return f"Error: Task {tid} already claimed by {task['owner']}"
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE tasks SET owner = %s, status = 'in_progress', updated_at = now() WHERE id = %s",
                    (owner, tid),
                )
            log.info("task #%d claimed by %s", tid, owner)
            return f"Claimed task #{tid} for {owner}"

    def list_unclaimed(self) -> list:
        """Return unclaimed, unblocked, pending tasks (for teammate auto-claim)."""
        if not self._enabled:
            return []
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM tasks
                WHERE status = 'pending' AND owner IS NULL AND blocked_by = '{}'
                ORDER BY id
            """)
            return [self._row_to_dict(r) for r in cur.fetchall()]
