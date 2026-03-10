"""Teammate manager and shutdown/plan protocols."""

import json
import threading
import time
import uuid

from config import WORKDIR, TEAM_DIR, INBOX_DIR, TASKS_DIR, POLL_INTERVAL, IDLE_TIMEOUT
from _bedrock import converse, to_bedrock_tools, user_msg, asst_msg, get_tool_uses
from tools import run_bash, run_read, run_write, run_edit


class TeammateManager:
    def __init__(self, bus, task_mgr, client, model):
        TEAM_DIR.mkdir(exist_ok=True)
        self.bus = bus
        self.task_mgr = task_mgr
        self.client = client
        self.model = model
        self.config_path = TEAM_DIR / "config.json"
        self.config = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {"team_name": "default", "members": []}

    def _save(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find(self, name: str) -> dict:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save()
        threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True).start()
        return f"Spawned '{name}' (role: {role})"

    def _set_status(self, name: str, status: str):
        member = self._find(name)
        if member:
            member["status"] = status
            self._save()

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
                    if m.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append(user_msg(json.dumps(m)))
                try:
                    msg, stop_reason = converse(self.client, self.model, sys_prompt, messages, tools=tools, max_tokens=8000)
                except Exception:
                    self._set_status(name, "shutdown")
                    return
                messages.append(msg)
                if stop_reason != "tool_use":
                    break
                results = []
                idle_requested = False
                for tu in get_tool_uses(msg["content"]):
                    if tu["name"] == "idle":
                        idle_requested = True
                        output = "Entering idle phase."
                    elif tu["name"] == "claim_task":
                        output = self.task_mgr.claim(tu["input"]["task_id"], name)
                    elif tu["name"] == "send_message":
                        output = self.bus.send(name, tu["input"]["to"], tu["input"]["content"])
                    else:
                        dispatch = {
                            "bash": lambda **kw: run_bash(kw["command"], auto_approve=True),
                            "read_file": lambda **kw: run_read(kw["path"]),
                            "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
                            "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
                        }
                        output = dispatch.get(tu["name"], lambda **kw: "Unknown")(**tu["input"])
                    results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": str(output)}]}})
                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break
            # -- IDLE PHASE --
            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for m in inbox:
                        if m.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append(user_msg(json.dumps(m)))
                    resume = True
                    break
                unclaimed = []
                for f in sorted(TASKS_DIR.glob("task_*.json")):
                    t = json.loads(f.read_text(encoding="utf-8"))
                    if t.get("status") == "pending" and not t.get("owner") and not t.get("blockedBy"):
                        unclaimed.append(t)
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
                    if len(messages) <= 3:
                        messages.insert(0, user_msg(f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>"))
                        messages.insert(1, asst_msg(f"I am {name}. Continuing."))
                    messages.append(user_msg(f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>"))
                    messages.append(asst_msg(f"Claimed task #{task['id']}. Working on it."))
                    resume = True
                    break
            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def remove(self, name: str) -> str:
        member = self._find(name)
        if not member:
            return f"Error: '{name}' not found"
        self.config["members"] = [m for m in self.config["members"] if m["name"] != name]
        self._save()
        inbox_path = INBOX_DIR / f"{name}.jsonl"
        if inbox_path.exists():
            inbox_path.unlink()
        return f"Removed '{name}' from team"

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]


# --- Shutdown / Plan protocols ---

shutdown_requests = {}
plan_requests = {}


def handle_shutdown_request(bus, teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    bus.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent to '{teammate}'"


def handle_plan_review(bus, request_id: str, approve: bool, feedback: str = "") -> str:
    req = plan_requests.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    bus.send("lead", req["from"], feedback, "plan_approval_response",
             {"request_id": request_id, "approve": approve, "feedback": feedback})
    return f"Plan {req['status']} for '{req['from']}'"
