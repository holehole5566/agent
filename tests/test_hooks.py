"""Tests for event hook system."""

import pytest
from pathlib import Path

from hooks import register, emit, load_hooks, list_hooks, clear, EVENTS, _event_to_func


@pytest.fixture(autouse=True)
def clean_hooks():
    """Clear hooks before each test."""
    clear()
    yield
    clear()


def test_register_and_emit():
    calls = []
    def my_hook(data):
        calls.append(data)

    register("message:received", my_hook)
    emit("message:received", {"query": "hello"})

    assert len(calls) == 1
    assert calls[0]["query"] == "hello"


def test_emit_no_hooks():
    """Emit with no registered hooks doesn't crash."""
    result = emit("message:received", {"query": "hello"})
    assert result == {"query": "hello"}


def test_emit_returns_data():
    """Emit returns the data dict."""
    result = emit("llm:before-request", {"messages": [1, 2, 3]})
    assert result["messages"] == [1, 2, 3]


def test_hook_can_modify_data():
    """Hooks can modify data in-place."""
    def add_timestamp(data):
        data["timestamp"] = 12345

    register("message:received", add_timestamp)
    result = emit("message:received", {"query": "hello"})
    assert result["timestamp"] == 12345


def test_hook_can_return_new_data():
    """Hooks can return a new dict to replace data."""
    def replace_data(data):
        return {"replaced": True}

    register("message:received", replace_data)
    result = emit("message:received", {"original": True})
    assert result == {"replaced": True}


def test_multiple_hooks_same_event():
    """Multiple hooks fire in registration order."""
    order = []
    def hook_a(data):
        order.append("a")
    def hook_b(data):
        order.append("b")

    register("message:received", hook_a)
    register("message:received", hook_b)
    emit("message:received", {})
    assert order == ["a", "b"]


def test_hook_error_doesnt_crash():
    """A failing hook doesn't stop other hooks."""
    calls = []
    def bad_hook(data):
        raise ValueError("oops")
    def good_hook(data):
        calls.append("ok")

    register("tool:before-execute", bad_hook)
    register("tool:before-execute", good_hook)
    emit("tool:before-execute", {})
    assert calls == ["ok"]


def test_register_unknown_event():
    """Registering an unknown event logs warning but doesn't crash."""
    register("nonexistent:event", lambda d: None)


def test_event_to_func():
    assert _event_to_func("message:received") == "on_message_received"
    assert _event_to_func("llm:before-request") == "on_llm_before_request"
    assert _event_to_func("tool:after-execute") == "on_tool_after_execute"


def test_load_hooks_from_dir(tmp_path):
    """Load hooks from .py files in a directory."""
    hook_file = tmp_path / "test_hook.py"
    hook_file.write_text(
        "results = []\n"
        "def on_message_received(data):\n"
        "    results.append(data.get('query'))\n"
    )
    load_hooks(tmp_path)
    emit("message:received", {"query": "test"})

    # Verify hook was registered and fired
    hooks_list = list_hooks()
    assert "message:received" in hooks_list
    assert "on_message_received" in hooks_list


def test_load_hooks_skips_underscore_files(tmp_path):
    """Files starting with _ are skipped."""
    (tmp_path / "_private.py").write_text(
        "def on_message_received(data): pass\n"
    )
    load_hooks(tmp_path)
    assert "No hooks" in list_hooks()


def test_load_hooks_skips_example_files(tmp_path):
    """Files starting with example_ are skipped."""
    (tmp_path / "example_tracker.py").write_text(
        "def on_message_received(data): pass\n"
    )
    load_hooks(tmp_path)
    assert "No hooks" in list_hooks()


def test_load_hooks_nonexistent_dir(tmp_path):
    """Loading from nonexistent dir doesn't crash."""
    load_hooks(tmp_path / "nonexistent")


def test_list_hooks_empty():
    assert "No hooks" in list_hooks()


def test_list_hooks_shows_registered():
    register("message:received", lambda d: None)
    result = list_hooks()
    assert "message:received" in result


def test_all_events_defined():
    """Verify all expected events exist."""
    expected = {
        "agent:bootstrap", "session:start", "session:end",
        "message:received", "message:sent",
        "llm:before-request", "llm:after-response",
        "tool:before-execute", "tool:after-execute",
    }
    assert EVENTS == expected
