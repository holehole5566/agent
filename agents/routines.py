"""Routines — cron-triggered automated tasks backed by PostgreSQL."""

import json
import logging
import threading
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from config import CFG
from _bedrock import get_client, get_model, converse, to_bedrock_tools, user_msg, get_text

log = logging.getLogger("routines")


def _next_cron_fire(schedule: str, after: datetime = None) -> datetime | None:
    """Compute next fire time for a 5-field cron expression.

    Uses croniter if available, otherwise returns None.
    """
    try:
        from croniter import croniter
    except ImportError:
        log.warning("croniter not installed — cron scheduling disabled")
        return None
    after = after or datetime.now(timezone.utc)
    try:
        cron = croniter(schedule, after)
        return cron.get_next(datetime).replace(tzinfo=timezone.utc)
    except (ValueError, KeyError) as e:
        log.error("invalid cron expression '%s': %s", schedule, e)
        return None


class RoutineManager:
    """CRUD for routines stored in PostgreSQL."""

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
            log.info("routine manager ready (PostgreSQL)")
        except Exception as e:
            log.error("routine manager init failed: %s", e)

    def _ensure_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS routines (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT DEFAULT '',
                    schedule TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT true,
                    cooldown_secs INTEGER DEFAULT 300,
                    next_fire_at TIMESTAMPTZ,
                    last_run_at TIMESTAMPTZ,
                    run_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_routines_next_fire
                ON routines (next_fire_at)
                WHERE enabled AND next_fire_at IS NOT NULL
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS routine_runs (
                    id SERIAL PRIMARY KEY,
                    routine_id INTEGER REFERENCES routines(id) ON DELETE CASCADE,
                    started_at TIMESTAMPTZ DEFAULT now(),
                    completed_at TIMESTAMPTZ,
                    status TEXT DEFAULT 'running',
                    result_summary TEXT,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_routine_runs_routine
                ON routine_runs (routine_id)
            """)

    def _row_to_dict(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
            "schedule": row["schedule"],
            "prompt": row["prompt"],
            "enabled": row["enabled"],
            "cooldown_secs": row["cooldown_secs"],
            "next_fire_at": str(row["next_fire_at"]) if row["next_fire_at"] else None,
            "last_run_at": str(row["last_run_at"]) if row["last_run_at"] else None,
            "run_count": row["run_count"],
        }

    def create(self, name: str, schedule: str, prompt: str,
               description: str = "", cooldown_secs: int = 300) -> str:
        if not self._enabled:
            return json.dumps({"error": "Routine store not available"})
        next_fire = _next_cron_fire(schedule)
        if next_fire is None:
            return json.dumps({"error": f"Invalid cron schedule: {schedule}"})
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO routines (name, description, schedule, prompt, cooldown_secs, next_fire_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    schedule = EXCLUDED.schedule,
                    prompt = EXCLUDED.prompt,
                    cooldown_secs = EXCLUDED.cooldown_secs,
                    next_fire_at = EXCLUDED.next_fire_at,
                    updated_at = now()
                RETURNING *
            """, (name, description, schedule, prompt, cooldown_secs, next_fire))
            row = cur.fetchone()
        routine = self._row_to_dict(row)
        log.info("created/updated routine '%s' (next: %s)", name, routine["next_fire_at"])
        return json.dumps(routine, indent=2)

    def delete(self, name: str) -> str:
        if not self._enabled:
            return "Routine store not available."
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM routines WHERE name = %s", (name,))
            if cur.rowcount == 0:
                return f"Routine '{name}' not found."
        log.info("deleted routine '%s'", name)
        return f"Deleted routine '{name}'."

    def list_all(self) -> str:
        if not self._enabled:
            return "Routine store not available."
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM routines ORDER BY name")
            rows = cur.fetchall()
        if not rows:
            return "No routines."
        lines = []
        for r in rows:
            status = "on" if r["enabled"] else "off"
            next_str = r["next_fire_at"].strftime("%Y-%m-%d %H:%M") if r["next_fire_at"] else "—"
            lines.append(f"  [{status}] {r['name']}  cron: {r['schedule']}  next: {next_str}  runs: {r['run_count']}")
        return "\n".join(lines)

    def toggle(self, name: str, enabled: bool) -> str:
        if not self._enabled:
            return "Routine store not available."
        with self.conn.cursor() as cur:
            cur.execute("UPDATE routines SET enabled = %s, updated_at = now() WHERE name = %s", (enabled, name))
            if cur.rowcount == 0:
                return f"Routine '{name}' not found."
        state = "enabled" if enabled else "disabled"
        log.info("routine '%s' %s", name, state)
        return f"Routine '{name}' {state}."

    def history(self, name: str, limit: int = 10) -> str:
        if not self._enabled:
            return "Routine store not available."
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT rr.* FROM routine_runs rr
                JOIN routines r ON r.id = rr.routine_id
                WHERE r.name = %s
                ORDER BY rr.started_at DESC LIMIT %s
            """, (name, limit))
            rows = cur.fetchall()
        if not rows:
            return f"No runs for routine '{name}'."
        lines = []
        for r in rows:
            ts = r["started_at"].strftime("%Y-%m-%d %H:%M") if r["started_at"] else ""
            summary = (r["result_summary"] or "")[:80]
            lines.append(f"  [{r['status']}] {ts}  {summary}")
        return "\n".join(lines)

    def get_due_routines(self) -> list:
        """Return routines whose next_fire_at has passed and cooldown is satisfied."""
        if not self._enabled:
            return []
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM routines
                WHERE enabled
                  AND next_fire_at IS NOT NULL
                  AND next_fire_at <= now()
                  AND (last_run_at IS NULL OR last_run_at + (cooldown_secs || ' seconds')::interval <= now())
                ORDER BY next_fire_at
            """)
            return [dict(r) for r in cur.fetchall()]

    def record_run_start(self, routine_id: int) -> int:
        """Create a run record and return its ID."""
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO routine_runs (routine_id) VALUES (%s) RETURNING id",
                (routine_id,),
            )
            return cur.fetchone()[0]

    def record_run_end(self, run_id: int, routine_id: int,
                       status: str, result_summary: str, schedule: str):
        """Update run record and routine runtime state."""
        next_fire = _next_cron_fire(schedule)
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE routine_runs
                SET completed_at = now(), status = %s, result_summary = %s
                WHERE id = %s
            """, (status, result_summary[:2000] if result_summary else None, run_id))
            cur.execute("""
                UPDATE routines
                SET last_run_at = now(), next_fire_at = %s,
                    run_count = run_count + 1, updated_at = now()
                WHERE id = %s
            """, (next_fire, routine_id))


class RoutineEngine:
    """Background cron ticker that executes due routines."""

    def __init__(self, manager: RoutineManager, gateway=None, check_interval: int = 15):
        self.manager = manager
        self.gateway = gateway
        self.check_interval = check_interval
        self._running = False
        self._thread = None
        self.client = get_client()
        self.model = get_model()

    def start(self):
        if not self.manager._enabled:
            log.info("routine engine disabled (no DB)")
            return
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, daemon=True, name="routine-engine")
        self._thread.start()
        log.info("routine engine started (interval: %ds)", self.check_interval)

    def stop(self):
        self._running = False

    def _tick_loop(self):
        while self._running:
            try:
                due = self.manager.get_due_routines()
                for routine in due:
                    threading.Thread(
                        target=self._execute,
                        args=(routine,),
                        daemon=True,
                        name=f"routine-{routine['name']}",
                    ).start()
            except Exception as e:
                log.error("routine tick error: %s", e)
            time.sleep(self.check_interval)

    def _execute(self, routine: dict):
        """Execute a single routine via a lightweight LLM call."""
        name = routine["name"]
        run_id = self.manager.record_run_start(routine["id"])
        log.info("executing routine '%s' (run #%d)", name, run_id)

        try:
            # Single-turn LLM call with basic tools
            tools_def = [
                {"name": "bash", "description": "Run command.",
                 "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
                {"name": "read_file", "description": "Read file.",
                 "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            ]
            tools = to_bedrock_tools(tools_def)
            from tools import run_bash, run_read
            handlers = {
                "bash": lambda **kw: run_bash(kw["command"]),
                "read_file": lambda **kw: run_read(kw["path"]),
            }

            sys_prompt = f"You are executing a scheduled routine named '{name}'. Complete the task and respond with a brief summary."
            messages = [user_msg(routine["prompt"])]

            result_text = ""
            for _ in range(5):  # max 5 iterations
                from _bedrock import get_tool_uses
                msg, stop_reason, _ = converse(
                    self.client, self.model, sys_prompt, messages,
                    tools=tools, max_tokens=4096,
                )
                messages.append(msg)
                if stop_reason != "tool_use":
                    result_text = get_text(msg.get("content", [])) or ""
                    break
                results = []
                for tu in get_tool_uses(msg["content"]):
                    h = handlers.get(tu["name"], lambda **kw: "Unknown tool")
                    output = str(h(**tu["input"]))[:50000]
                    results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": output}]}})
                messages.append({"role": "user", "content": results})

            status = "ok"
            self.manager.record_run_end(run_id, routine["id"], status, result_text, routine["schedule"])
            log.info("routine '%s' completed: %s", name, result_text[:100])

            # Notify via gateway if available
            self._notify(routine, result_text)

        except Exception as e:
            log.error("routine '%s' failed: %s", name, e)
            self.manager.record_run_end(run_id, routine["id"], "failed", str(e), routine["schedule"])
            self._notify(routine, f"Routine '{name}' failed: {e}")

    def _notify(self, routine: dict, text: str):
        """Send routine result to the user via the first available channel."""
        if not self.gateway or not text:
            return
        for channel in self.gateway.channels.values():
            owner_id = getattr(channel, "owner_id", None)
            if owner_id:
                prefix = f"🔄 **Routine: {routine['name']}**\n\n"
                channel.send_response(owner_id, prefix + text)
                return
