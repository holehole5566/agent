"""Agent orchestrator — tool dispatch, tool definitions, and main loop."""

import json
import logging

from config import CFG, WORKDIR, VALID_MSG_TYPES, TOKEN_THRESHOLD
from _bedrock import (
    get_client, get_model, converse, converse_stream, to_bedrock_tools,
    user_msg, asst_msg, get_tool_uses, get_text,
)
from tools import run_bash, run_read, run_write, run_edit
from todos import TodoManager
from tasks import TaskManager
from background import BackgroundManager
from messaging import MessageBus
from skills import SkillLoader
from compression import estimate_tokens, microcompact, auto_compact
from team import TeammateManager, handle_shutdown_request, handle_plan_review
from permissions import ALL_SCOPES, DEFAULT_TEAMMATE_SCOPES, check_permission, get_required_scope
from hooks import emit
from workspace import Workspace, MEMORY_PATH
from routines import RoutineManager

from config import SKILLS_DIR

log = logging.getLogger("agent")

# --- Global instances ---
client = get_client()
MODEL = get_model()

TODO = TodoManager()
SKILLS = SkillLoader(SKILLS_DIR)
TASK_MGR = TaskManager()
BG = BackgroundManager()
BUS = MessageBus()
TEAM = TeammateManager(BUS, TASK_MGR, client, MODEL)
WORKSPACE = Workspace()
ROUTINE_MGR = RoutineManager()

_memory_content = WORKSPACE.read_memory() if WORKSPACE.enabled else ""
_memory_block = f"\n\n## Long-Term Memory\n\n{_memory_content}" if _memory_content else ""
SYSTEM = f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks.
Prefer task_create/task_update/task_list for multi-step work. Use TodoWrite for short checklists.
Use task for subagent delegation. Use load_skill for specialized knowledge.
Use routine_create for scheduled/recurring tasks (cron). Use routine_list to check existing routines.
Use memory_search before answering questions about prior work or context.
Use memory_write to persist important facts, decisions, and session notes.
Skills: {SKILLS.descriptions()}{_memory_block}"""


def _memory_write(content: str, target: str = "daily_log", append: bool = True, **_) -> dict:
    """Route memory_write tool to the right workspace method."""
    if target == "memory":
        if append:
            return WORKSPACE.append_memory(content)
        return WORKSPACE.write(MEMORY_PATH, content)
    elif target == "daily_log":
        return WORKSPACE.append_daily_log(content)
    else:
        # Custom path
        if append:
            return WORKSPACE.append(target, content)
        return WORKSPACE.write(target, content)


# --- Subagent (non-streaming, internal) ---
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
        msg, stop_reason, _ = converse(client, MODEL, "", sub_msgs, tools=sub_tools, max_tokens=8000)
        sub_msgs.append(msg)
        if stop_reason != "tool_use":
            break
        results = []
        for tu in get_tool_uses(msg["content"]):
            h = sub_handlers.get(tu["name"], lambda **kw: "Unknown tool")
            results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": str(h(**tu["input"]))[:50000]}]}})
        sub_msgs.append({"role": "user", "content": results})
    if msg:
        return get_text(msg["content"]) or "(no summary)"
    return "(subagent failed)"


# --- Tool handlers ---
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
    "spawn_teammate":   lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"], scopes=set(kw.get("scopes", [])) or None),
    "list_teammates":   lambda **kw: TEAM.list_all(),
    "send_message":     lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":       lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":        lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
    "remove_teammate":  lambda **kw: TEAM.remove(kw["name"]),
    "shutdown_request": lambda **kw: handle_shutdown_request(BUS, kw["teammate"]),
    "plan_approval":    lambda **kw: handle_plan_review(BUS, kw["request_id"], kw["approve"], kw.get("feedback", "")),
    "idle":             lambda **kw: "Lead does not idle.",
    "claim_task":       lambda **kw: TASK_MGR.claim(kw["task_id"], "lead"),
    "routine_create":   lambda **kw: ROUTINE_MGR.create(kw["name"], kw["schedule"], kw["prompt"], kw.get("description", ""), kw.get("cooldown_secs", 300)),
    "routine_list":     lambda **kw: ROUTINE_MGR.list_all(),
    "routine_delete":   lambda **kw: ROUTINE_MGR.delete(kw["name"]),
    "routine_history":  lambda **kw: ROUTINE_MGR.history(kw["name"], kw.get("limit", 10)),
    "routine_toggle":   lambda **kw: ROUTINE_MGR.toggle(kw["name"], kw["enabled"]),
    "memory_search":    lambda **kw: json.dumps(WORKSPACE.search(kw["query"], kw.get("limit", 5)), indent=2, default=str),
    "memory_write":     lambda **kw: json.dumps(_memory_write(**kw), default=str),
    "memory_read":      lambda **kw: json.dumps(WORKSPACE.read(kw["path"]) or {"error": "not found"}, default=str),
    "memory_list":      lambda **kw: json.dumps(WORKSPACE.list_dir(kw.get("path", "")), default=str),
}

# --- Tool definitions ---
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
    {"name": "spawn_teammate", "description": "Spawn teammate. Scopes control what tools the teammate can use (default: read,write,execute).", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}, "scopes": {"type": "array", "items": {"type": "string", "enum": ["read", "write", "execute", "admin", "agent"]}, "description": "Permission scopes (default: read,write,execute)"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List teammates.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send message.", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read lead inbox.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Broadcast to all.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
    {"name": "remove_teammate", "description": "Force-remove a teammate (use when shutdown_request fails or teammate is stuck).", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "shutdown_request", "description": "Request graceful shutdown.", "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "plan_approval", "description": "Approve/reject plan.", "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},
    {"name": "idle", "description": "Enter idle.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "claim_task", "description": "Claim task.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    {"name": "routine_create", "description": "Create or update a scheduled routine. Uses 5-field cron syntax (min hour day month weekday).", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "schedule": {"type": "string", "description": "Cron expression, e.g. '0 9 * * *' for daily 9am UTC"}, "prompt": {"type": "string", "description": "The task prompt to execute"}, "description": {"type": "string"}, "cooldown_secs": {"type": "integer", "description": "Min seconds between runs (default 300)"}}, "required": ["name", "schedule", "prompt"]}},
    {"name": "routine_list", "description": "List all routines with status.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "routine_delete", "description": "Delete a routine by name.", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "routine_history", "description": "Show recent runs of a routine.", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["name"]}},
    {"name": "routine_toggle", "description": "Enable or disable a routine.", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "enabled": {"type": "boolean"}}, "required": ["name", "enabled"]}},
    {"name": "memory_search", "description": "Search workspace memories (hybrid FTS + semantic). Call before answering questions about prior work.", "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Natural language search query"}, "limit": {"type": "integer", "description": "Max results (default 5)"}}, "required": ["query"]}},
    {"name": "memory_write", "description": "Write to persistent memory. target: 'memory' for MEMORY.md (curated facts), 'daily_log' for today's timestamped log, or a custom path like 'projects/notes.md'.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}, "target": {"type": "string", "description": "'memory', 'daily_log', or custom path", "default": "daily_log"}, "append": {"type": "boolean", "description": "Append (true) or overwrite (false)", "default": True}}, "required": ["content"]}},
    {"name": "memory_read", "description": "Read a workspace file by path.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "memory_list", "description": "List workspace files/directories.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "Directory path (empty for root)", "default": ""}}}},
]
TOOLS = to_bedrock_tools(TOOLS_DEF)


# --- Agent loop ---
def agent_loop(messages: list, on_text=None):
    """Run the agent loop. on_text: optional callback for streaming text chunks."""
    rounds_without_todo = 0
    while True:
        # Compression pipeline
        microcompact(messages)
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            log.info("auto-compact triggered")
            messages[:] = auto_compact(messages, client, MODEL)
        # Drain background notifications + check lead inbox
        injections = []
        notifs = BG.drain()
        if notifs:
            txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            injections.append(f"<background-results>\n{txt}\n</background-results>")
        inbox = BUS.read_inbox("lead")
        if inbox:
            injections.append(f"<inbox>{json.dumps(inbox, indent=2)}</inbox>")
        if injections:
            if messages and messages[-1]["role"] == "user":
                for inj in injections:
                    messages[-1]["content"].append({"text": inj})
            else:
                messages.append(user_msg("\n".join(injections)))
        # LLM call (streaming — prints text tokens to stdout)
        emit("llm:before-request", {"messages": messages, "system": SYSTEM})
        msg, stop_reason, usage = converse_stream(client, MODEL, SYSTEM, messages, tools=TOOLS, max_tokens=8000, on_text=on_text)
        emit("llm:after-response", {"message": msg, "stop_reason": stop_reason, "usage": usage})
        messages.append(msg)
        if stop_reason != "tool_use":
            emit("message:sent", {"message": msg})
            return
        # Tool execution
        results = []
        used_todo = False
        manual_compress = False
        for tu in get_tool_uses(msg["content"]):
            if tu["name"] == "compress":
                manual_compress = True
            handler = TOOL_HANDLERS.get(tu["name"])
            emit("tool:before-execute", {"name": tu["name"], "input": tu["input"]})
            try:
                output = handler(**tu["input"]) if handler else f"Unknown tool: {tu['name']}"
            except Exception as e:
                log.error("tool %s failed: %s", tu["name"], e)
                output = f"Error: {e}"
            emit("tool:after-execute", {"name": tu["name"], "input": tu["input"], "output": str(output)[:500]})
            if tu["name"] == "bash":
                print(f"  > bash: {tu['input'].get('command', '')[:120]}")
            else:
                print(f"  > {tu['name']}")
            results.append({"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": str(output)}]}})
            if tu["name"] == "TodoWrite":
                used_todo = True
        # Nag reminder
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if TODO.has_open_items() and rounds_without_todo >= 3:
            results.insert(0, {"text": "<reminder>Update your todos.</reminder>"})
        messages.append({"role": "user", "content": results})
        # Manual compress
        if manual_compress:
            log.info("manual compact")
            messages[:] = auto_compact(messages, client, MODEL)
