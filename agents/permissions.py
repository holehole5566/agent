"""Scope-based authorization for tools."""

import logging

log = logging.getLogger("permissions")

# Scope → tool name mapping
SCOPES = {
    "read": {
        "read_file", "task_list", "task_get", "list_teammates",
        "read_inbox", "check_background", "load_skill",
    },
    "write": {
        "write_file", "edit_file", "TodoWrite",
        "task_create", "task_update", "claim_task",
    },
    "execute": {
        "bash", "background_run",
    },
    "admin": {
        "spawn_teammate", "remove_teammate", "shutdown_request",
        "broadcast", "send_message", "plan_approval", "compress",
    },
    "agent": {
        "task",
    },
}

ALL_SCOPES = set(SCOPES.keys())
DEFAULT_TEAMMATE_SCOPES = {"read", "write", "execute"}

# Reverse lookup: tool_name → required scope
_TOOL_TO_SCOPE = {}
for scope, tools in SCOPES.items():
    for tool in tools:
        _TOOL_TO_SCOPE[tool] = scope


def get_required_scope(tool_name: str) -> str | None:
    """Return the scope required for a tool, or None if not mapped."""
    return _TOOL_TO_SCOPE.get(tool_name)


def check_permission(tool_name: str, granted_scopes: set) -> bool:
    """Check if a tool is allowed given the granted scopes."""
    required = get_required_scope(tool_name)
    if required is None:
        return True  # unmapped tools (e.g. idle) are allowed
    return required in granted_scopes


def filter_tools(tools_def: list, granted_scopes: set) -> list:
    """Filter tool definitions to only those allowed by granted scopes."""
    return [t for t in tools_def if check_permission(t["name"], granted_scopes)]
