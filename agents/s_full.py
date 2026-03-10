#!/usr/bin/env python3
"""
s_full.py - Full Reference Agent (Bedrock Converse API)

Capstone implementation combining every mechanism from s01-s11.
NOT a teaching session -- this is the "put it all together" reference.

    REPL commands: /compact /tasks /team /inbox
"""

import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from queue import Queue

from _bedrock import (
    get_client, get_model, converse, to_bedrock_tools,
    user_msg, asst_msg, get_tool_uses, get_text,
)

WORKDIR = Path.cwd()
client = get_client()
MODEL = get_model()

TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = WORKDIR / ".tasks"
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOKEN_THRESHOLD = 100000
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
VALID_MSG_TYPES = {"message", "broadcast", "shutdown_request", "shutdown_response", "plan_approval_response"}


# === SECTION: base_tools ===
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR): raise ValueError(f"Path escapes workspace: {p}")
    return path

BLOCKED_COMMANDS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
APPROVE_PATTERNS = ["rm ", "rmdir", "del ", "mv ", "move ", "git push", "git reset", "git checkout --", "git clean"]

def run_bash(command: str, auto_approve: bool = False) -> str:
    if any(d in command for d in BLOCKED_COMMANDS):
        return "Error: Dangerous command blocked"
    if not auto_approve and any(p in command for p in APPROVE_PATTERNS):
        print(f"\n  ⚠ Command requires approval: {command}")
        answer = input("  Approve? [y/N] ").strip().lower()
        if answer != "y":
            return "Error: Command rejected by user"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired: return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if limit and limit < len(lines): lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e: return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path); fp.parent.mkdir(parents=True, exist_ok=True); fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e: return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path); c = fp.read_text(encoding="utf-8")
        if old_text not in c: return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1)); return f"Edited {path}"
    except Exception as e: return f"Error: {e}"


# === SECTION: todos (s03) ===
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        validated, ip = [], 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            af = str(item.get("activeForm", "")).strip()
            if not content: raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"): raise ValueError(f"Item {i}: invalid status")
            if not af: raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress": ip += 1
            validated.append({"content": content, "status": status, "activeForm": af})
        if len(validated) > 20: raise ValueError("Max 20 todos")
        if ip > 1: raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items: return "No todos."
        lines = []
        for item in self.items:
            m = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(item["status"], "[?]")
            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{m} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        return any(item.get("status") != "completed" for item in self.items)


# === SECTION: subagent (s04) ===
def run_subagent(prompt: str, agent_type: str = "Explore") -> str:
    sub_tools_def = [
        {"name": "bash", "description": "Run command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    ]
    if agent_type != "Explore":
        sub_tools_def += [
            {"name": "write_file", "description": "Write file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        ]
    sub_tools = to_bedrock_tools(sub_tools_def)
    sub_handlers = {
        "bash": lambda **kw: run_bash(kw["command"]),
        "read_file": lambda **kw: run_read(kw["path"]),
        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    }
    sub_msgs = [user_msg(prompt)]
    msg = None
    for _ in range(30):
        msg, stop_reason = converse(client, MODEL, "", sub_msgs, tools=sub_tools, max_tokens=8000)
        sub_msgs.append(msg)
        if stop_reason != "tool_use": break
        results = []
        for tu in get_tool_uses(msg["content"]):
            h = sub_handlers.get(tu["name"], lambda **kw: "Unknown tool")
            results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": str(h(**tu["input"]))[:50000]}]}})
        sub_msgs.append({"role": "user", "content": results})
    if msg:
        return get_text(msg["content"]) or "(no summary)"
    return "(subagent failed)"


# === SECTION: skills (s05) ===
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills = {}
        if skills_dir.exists():
            for f in sorted(skills_dir.rglob("SKILL.md")):
                text = f.read_text(encoding="utf-8")
                match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                meta, body = {}, text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1); meta[k.strip()] = v.strip()
                    body = match.group(2).strip()
                self.skills[meta.get("name", f.parent.name)] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        if not self.skills: return "(no skills)"
        return "\n".join(f"  - {n}: {s['meta'].get('description', '-')}" for n, s in self.skills.items())

    def load(self, name: str) -> str:
        s = self.skills.get(name)
        if not s: return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{s['body']}\n</skill>"


# === SECTION: compression (s06) ===
def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4

def microcompact(messages: list):
    tool_results = []
    for msg in messages:
        if msg["role"] == "user":
            for block in msg.get("content", []):
                if isinstance(block, dict) and "toolResult" in block:
                    tool_results.append(block)
    if len(tool_results) <= 3: return
    for tr in tool_results[:-3]:
        inner = tr["toolResult"].get("content", [])
        if inner and isinstance(inner[0], dict) and len(inner[0].get("text", "")) > 100:
            inner[0]["text"] = "[cleared]"

def auto_compact(messages: list) -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages: f.write(json.dumps(msg, default=str) + "\n")
    conv_text = json.dumps(messages, default=str)[:80000]
    summary_msg, _ = converse(client, MODEL, "", [user_msg(f"Summarize for continuity:\n{conv_text}")], max_tokens=2000)
    summary = get_text(summary_msg["content"])
    return [user_msg(f"[Compressed. Transcript: {path}]\n{summary}"), asst_msg("Understood. Continuing with summary context.")]


# === SECTION: file_tasks (s07) ===
class TaskManager:
    def __init__(self):
        TASKS_DIR.mkdir(exist_ok=True)
        self._lock = threading.Lock()

    def _next_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in TASKS_DIR.glob("task_*.json")]
        return max(ids, default=0) + 1

    def _load(self, tid: int) -> dict:
        p = TASKS_DIR / f"task_{tid}.json"
        if not p.exists(): raise ValueError(f"Task {tid} not found")
        return json.loads(p.read_text(encoding="utf-8"))

    def _save(self, task: dict):
        (TASKS_DIR / f"task_{task['id']}.json").write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        task = {"id": self._next_id(), "subject": subject, "description": description,
                "status": "pending", "owner": None, "blockedBy": [], "blocks": []}
        self._save(task); return json.dumps(task, indent=2)

    def get(self, tid: int) -> str: return json.dumps(self._load(tid), indent=2)

    def update(self, tid: int, status: str = None, add_blocked_by: list = None, add_blocks: list = None) -> str:
        task = self._load(tid)
        if status:
            task["status"] = status
            if status == "completed":
                for f in TASKS_DIR.glob("task_*.json"):
                    t = json.loads(f.read_text(encoding="utf-8"))
                    if tid in t.get("blockedBy", []): t["blockedBy"].remove(tid); self._save(t)
            if status == "deleted":
                (TASKS_DIR / f"task_{tid}.json").unlink(missing_ok=True); return f"Task {tid} deleted"
        if add_blocked_by: task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if add_blocks: task["blocks"] = list(set(task["blocks"] + add_blocks))
        self._save(task); return json.dumps(task, indent=2)

    def list_all(self) -> str:
        tasks = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(TASKS_DIR.glob("task_*.json"))]
        if not tasks: return "No tasks."
        lines = []
        for t in tasks:
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
            task["owner"] = owner; task["status"] = "in_progress"
            self._save(task); return f"Claimed task #{tid} for {owner}"


# === SECTION: background (s08) ===
class BackgroundManager:
    def __init__(self):
        self.tasks = {}; self.notifications = Queue()

    def run(self, command: str, timeout: int = 120) -> str:
        tid = str(uuid.uuid4())[:8]
        self.tasks[tid] = {"status": "running", "command": command, "result": None}
        threading.Thread(target=self._exec, args=(tid, command, timeout), daemon=True).start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int):
        try:
            r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
            output = ((r.stdout or "") + (r.stderr or "")).strip()[:50000]
            self.tasks[tid].update({"status": "completed", "result": output or "(no output)"})
        except Exception as e:
            self.tasks[tid].update({"status": "error", "result": str(e)})
        self.notifications.put({"task_id": tid, "status": self.tasks[tid]["status"], "result": self.tasks[tid]["result"][:500]})

    def check(self, tid: str = None) -> str:
        if tid:
            t = self.tasks.get(tid)
            return f"[{t['status']}] {t.get('result', '(running)')}" if t else f"Unknown: {tid}"
        return "\n".join(f"{k}: [{v['status']}] {v['command'][:60]}" for k, v in self.tasks.items()) or "No bg tasks."

    def drain(self) -> list:
        notifs = []
        while not self.notifications.empty(): notifs.append(self.notifications.get_nowait())
        return notifs


# === SECTION: messaging (s09) ===
class MessageBus:
    def __init__(self):
        INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str, msg_type: str = "message", extra: dict = None) -> str:
        msg = {"type": msg_type, "from": sender, "content": content, "timestamp": time.time()}
        if extra: msg.update(extra)
        with open(INBOX_DIR / f"{to}.jsonl", "a") as f: f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        path = INBOX_DIR / f"{name}.jsonl"
        if not path.exists(): return []
        msgs = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines() if l]
        path.write_text(""); return msgs

    def broadcast(self, sender: str, content: str, names: list) -> str:
        count = 0
        for n in names:
            if n != sender: self.send(sender, n, content, "broadcast"); count += 1
        return f"Broadcast to {count} teammates"


# === SECTION: shutdown + plan (s10) ===
shutdown_requests = {}
plan_requests = {}


# === SECTION: team (s09/s11) ===
class TeammateManager:
    def __init__(self, bus: MessageBus, task_mgr: TaskManager):
        TEAM_DIR.mkdir(exist_ok=True)
        self.bus = bus; self.task_mgr = task_mgr
        self.config_path = TEAM_DIR / "config.json"
        self.config = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {"team_name": "default", "members": []}

    def _save(self): self.config_path.write_text(json.dumps(self.config, indent=2))
    def _find(self, name: str) -> dict:
        for m in self.config["members"]:
            if m["name"] == name: return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"): return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"; member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save()
        threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True).start()
        return f"Spawned '{name}' (role: {role})"

    def _set_status(self, name: str, status: str):
        member = self._find(name)
        if member: member["status"] = status; self._save()

    def _loop(self, name: str, role: str, prompt: str):
        team_name = self.config["team_name"]
        sys_prompt = (f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
                      f"Use idle when done with current work. You may auto-claim tasks.")
        messages = [user_msg(prompt)]
        tools_def = [
            {"name": "bash", "description": "Run command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "send_message", "description": "Send message.", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}}, "required": ["to", "content"]}},
            {"name": "idle", "description": "Signal no more work.", "input_schema": {"type": "object", "properties": {}}},
            {"name": "claim_task", "description": "Claim task by ID.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
        ]
        tools = to_bedrock_tools(tools_def)
        while True:
            # -- WORK PHASE --
            for _ in range(50):
                inbox = self.bus.read_inbox(name)
                for m in inbox:
                    if m.get("type") == "shutdown_request": self._set_status(name, "shutdown"); return
                    messages.append(user_msg(json.dumps(m)))
                try:
                    msg, stop_reason = converse(client, MODEL, sys_prompt, messages, tools=tools, max_tokens=8000)
                except Exception: self._set_status(name, "shutdown"); return
                messages.append(msg)
                if stop_reason != "tool_use": break
                results = []; idle_requested = False
                for tu in get_tool_uses(msg["content"]):
                    if tu["name"] == "idle": idle_requested = True; output = "Entering idle phase."
                    elif tu["name"] == "claim_task": output = self.task_mgr.claim(tu["input"]["task_id"], name)
                    elif tu["name"] == "send_message": output = self.bus.send(name, tu["input"]["to"], tu["input"]["content"])
                    else:
                        dispatch = {"bash": lambda **kw: run_bash(kw["command"], auto_approve=True), "read_file": lambda **kw: run_read(kw["path"]),
                                    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
                                    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])}
                        output = dispatch.get(tu["name"], lambda **kw: "Unknown")(**tu["input"])
                    # Suppress verbose teammate output to avoid polluting the input prompt
                    results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": str(output)}]}})
                messages.append({"role": "user", "content": results})
                if idle_requested: break
            # -- IDLE PHASE --
            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for m in inbox:
                        if m.get("type") == "shutdown_request": self._set_status(name, "shutdown"); return
                        messages.append(user_msg(json.dumps(m)))
                    resume = True; break
                unclaimed = []
                for f in sorted(TASKS_DIR.glob("task_*.json")):
                    t = json.loads(f.read_text(encoding="utf-8"))
                    if t.get("status") == "pending" and not t.get("owner") and not t.get("blockedBy"): unclaimed.append(t)
                if unclaimed:
                    task = unclaimed[0]; self.task_mgr.claim(task["id"], name)
                    if len(messages) <= 3:
                        messages.insert(0, user_msg(f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>"))
                        messages.insert(1, asst_msg(f"I am {name}. Continuing."))
                    messages.append(user_msg(f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>"))
                    messages.append(asst_msg(f"Claimed task #{task['id']}. Working on it."))
                    resume = True; break
            if not resume: self._set_status(name, "shutdown"); return
            self._set_status(name, "working")

    def list_all(self) -> str:
        if not self.config["members"]: return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]: lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def remove(self, name: str) -> str:
        member = self._find(name)
        if not member: return f"Error: '{name}' not found"
        self.config["members"] = [m for m in self.config["members"] if m["name"] != name]
        self._save()
        # Clean up inbox
        inbox_path = INBOX_DIR / f"{name}.jsonl"
        if inbox_path.exists(): inbox_path.unlink()
        return f"Removed '{name}' from team"

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]


# === SECTION: global_instances ===
TODO = TodoManager()
SKILLS = SkillLoader(SKILLS_DIR)
TASK_MGR = TaskManager()
BG = BackgroundManager()
BUS = MessageBus()
TEAM = TeammateManager(BUS, TASK_MGR)

SYSTEM = f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks.
Prefer task_create/task_update/task_list for multi-step work. Use TodoWrite for short checklists.
Use task for subagent delegation. Use load_skill for specialized knowledge.
Skills: {SKILLS.descriptions()}"""


# === SECTION: shutdown_protocol (s10) ===
def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent to '{teammate}'"

def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    req = plan_requests.get(request_id)
    if not req: return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    BUS.send("lead", req["from"], feedback, "plan_approval_response", {"request_id": request_id, "approve": approve, "feedback": feedback})
    return f"Plan {req['status']} for '{req['from']}'"


# === SECTION: tool_dispatch ===
TOOL_HANDLERS = {
    "bash":             lambda **kw: run_bash(kw["command"]),
    "read_file":        lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "TodoWrite":        lambda **kw: TODO.update(kw["items"]),
    "task":             lambda **kw: run_subagent(kw["prompt"], kw.get("agent_type", "Explore")),
    "load_skill":       lambda **kw: SKILLS.load(kw["name"]),
    "compress":         lambda **kw: "Compressing...",
    "background_run":   lambda **kw: BG.run(kw["command"], kw.get("timeout", 120)),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),
    "task_create":      lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", "")),
    "task_get":         lambda **kw: TASK_MGR.get(kw["task_id"]),
    "task_update":      lambda **kw: TASK_MGR.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("add_blocks")),
    "task_list":        lambda **kw: TASK_MGR.list_all(),
    "spawn_teammate":   lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates":   lambda **kw: TEAM.list_all(),
    "send_message":     lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":       lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":        lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
    "remove_teammate":  lambda **kw: TEAM.remove(kw["name"]),
    "shutdown_request": lambda **kw: handle_shutdown_request(kw["teammate"]),
    "plan_approval":    lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
    "idle":             lambda **kw: "Lead does not idle.",
    "claim_task":       lambda **kw: TASK_MGR.claim(kw["task_id"], "lead"),
}

TOOLS_DEF = [
    {"name": "bash", "description": "Run a shell command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "TodoWrite", "description": "Update task tracking list.", "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "activeForm": {"type": "string"}}, "required": ["content", "status", "activeForm"]}}}, "required": ["items"]}},
    {"name": "task", "description": "Spawn a subagent.", "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}, "agent_type": {"type": "string", "enum": ["Explore", "general-purpose"]}}, "required": ["prompt"]}},
    {"name": "load_skill", "description": "Load specialized knowledge.", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "compress", "description": "Compress conversation.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "background_run", "description": "Run in background.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}},
    {"name": "check_background", "description": "Check background task.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
    {"name": "task_create", "description": "Create persistent task.", "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
    {"name": "task_get", "description": "Get task by ID.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    {"name": "task_update", "description": "Update task.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]}, "add_blocked_by": {"type": "array", "items": {"type": "integer"}}, "add_blocks": {"type": "array", "items": {"type": "integer"}}}, "required": ["task_id"]}},
    {"name": "task_list", "description": "List all tasks.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "spawn_teammate", "description": "Spawn teammate.", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List teammates.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send message.", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read lead inbox.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Broadcast to all.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
    {"name": "remove_teammate", "description": "Force-remove a teammate (use when shutdown_request fails or teammate is stuck).", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "shutdown_request", "description": "Request graceful shutdown.", "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "plan_approval", "description": "Approve/reject plan.", "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},
    {"name": "idle", "description": "Enter idle.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "claim_task", "description": "Claim task.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
]
TOOLS = to_bedrock_tools(TOOLS_DEF)


# === SECTION: agent_loop ===
def agent_loop(messages: list):
    rounds_without_todo = 0
    while True:
        # s06: compression pipeline
        microcompact(messages)
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            print("[auto-compact triggered]")
            messages[:] = auto_compact(messages)
        # s08: drain background notifications + s10: check lead inbox
        injections = []
        notifs = BG.drain()
        if notifs:
            txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            injections.append(f"<background-results>\n{txt}\n</background-results>")
        inbox = BUS.read_inbox("lead")
        if inbox:
            injections.append(f"<inbox>{json.dumps(inbox, indent=2)}</inbox>")
        if injections:
            # Ensure conversation ends with a user message for Bedrock
            if messages and messages[-1]["role"] == "user":
                # Append to existing user message content
                for inj in injections:
                    messages[-1]["content"].append({"text": inj})
            else:
                messages.append(user_msg("\n".join(injections)))
        # LLM call
        msg, stop_reason = converse(client, MODEL, SYSTEM, messages, tools=TOOLS, max_tokens=8000)
        messages.append(msg)
        if stop_reason != "tool_use":
            return
        # Tool execution
        results = []
        used_todo = False
        manual_compress = False
        for tu in get_tool_uses(msg["content"]):
            if tu["name"] == "compress":
                manual_compress = True
            handler = TOOL_HANDLERS.get(tu["name"])
            try:
                output = handler(**tu["input"]) if handler else f"Unknown tool: {tu['name']}"
            except Exception as e:
                output = f"Error: {e}"
            if tu["name"] == "bash":
                print(f"  > bash: {tu['input'].get('command', '')[:120]}")
            else:
                print(f"  > {tu['name']}")
            results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": str(output)}]}})
            if tu["name"] == "TodoWrite":
                used_todo = True
        # s03: nag reminder
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if TODO.has_open_items() and rounds_without_todo >= 3:
            results.insert(0, {"text": "<reminder>Update your todos.</reminder>"})
        messages.append({"role": "user", "content": results})
        # s06: manual compress
        if manual_compress:
            print("[manual compact]")
            messages[:] = auto_compact(messages)


