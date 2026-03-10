"""Tests for scope-based authorization."""

from permissions import (
    check_permission, get_required_scope, filter_tools,
    ALL_SCOPES, DEFAULT_TEAMMATE_SCOPES, SCOPES,
)


def test_all_scopes_contains_expected():
    assert "read" in ALL_SCOPES
    assert "write" in ALL_SCOPES
    assert "execute" in ALL_SCOPES
    assert "admin" in ALL_SCOPES
    assert "agent" in ALL_SCOPES


def test_default_teammate_scopes():
    assert DEFAULT_TEAMMATE_SCOPES == {"read", "write", "execute"}
    assert "admin" not in DEFAULT_TEAMMATE_SCOPES
    assert "agent" not in DEFAULT_TEAMMATE_SCOPES


def test_get_required_scope():
    assert get_required_scope("bash") == "execute"
    assert get_required_scope("read_file") == "read"
    assert get_required_scope("write_file") == "write"
    assert get_required_scope("spawn_teammate") == "admin"
    assert get_required_scope("task") == "agent"
    assert get_required_scope("idle") is None  # unmapped


def test_check_permission_allowed():
    assert check_permission("bash", {"execute"})
    assert check_permission("read_file", {"read", "write"})
    assert check_permission("write_file", {"read", "write", "execute"})


def test_check_permission_denied():
    assert not check_permission("bash", {"read"})
    assert not check_permission("spawn_teammate", {"read", "write", "execute"})
    assert not check_permission("task", {"read", "write", "execute"})


def test_check_permission_unmapped_tool_allowed():
    assert check_permission("idle", set())
    assert check_permission("nonexistent_tool", {"read"})


def test_lead_has_all_permissions():
    for scope, tools in SCOPES.items():
        for tool in tools:
            assert check_permission(tool, ALL_SCOPES), f"{tool} should be allowed with ALL_SCOPES"


def test_filter_tools():
    tools_def = [
        {"name": "bash", "description": "Run cmd.", "input_schema": {}},
        {"name": "read_file", "description": "Read.", "input_schema": {}},
        {"name": "write_file", "description": "Write.", "input_schema": {}},
        {"name": "spawn_teammate", "description": "Spawn.", "input_schema": {}},
        {"name": "idle", "description": "Idle.", "input_schema": {}},
    ]

    # Read-only should only get read_file and idle (unmapped)
    filtered = filter_tools(tools_def, {"read"})
    names = {t["name"] for t in filtered}
    assert "read_file" in names
    assert "idle" in names
    assert "bash" not in names
    assert "write_file" not in names
    assert "spawn_teammate" not in names


def test_filter_tools_default_teammate():
    tools_def = [
        {"name": "bash", "description": "Run cmd.", "input_schema": {}},
        {"name": "read_file", "description": "Read.", "input_schema": {}},
        {"name": "write_file", "description": "Write.", "input_schema": {}},
        {"name": "spawn_teammate", "description": "Spawn.", "input_schema": {}},
    ]

    filtered = filter_tools(tools_def, DEFAULT_TEAMMATE_SCOPES)
    names = {t["name"] for t in filtered}
    assert "bash" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "spawn_teammate" not in names  # admin scope needed
