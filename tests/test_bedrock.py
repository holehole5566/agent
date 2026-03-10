"""Tests for Bedrock helpers and streaming."""

import json
from unittest.mock import MagicMock

from _bedrock import (
    user_msg, asst_msg, get_text, get_tool_uses,
    to_bedrock_tools, converse, converse_stream, _clean_content,
)
from conftest import make_converse_response, make_stream_events


# --- Message helpers ---

def test_user_msg():
    msg = user_msg("hello")
    assert msg["role"] == "user"
    assert msg["content"] == [{"text": "hello"}]


def test_user_msg_empty_fallback():
    msg = user_msg("")
    assert msg["content"][0]["text"] == "(empty)"


def test_asst_msg():
    msg = asst_msg("world")
    assert msg["role"] == "assistant"
    assert msg["content"] == [{"text": "world"}]


def test_asst_msg_none_fallback():
    msg = asst_msg(None)
    assert msg["content"][0]["text"] == "(empty)"


# --- Response parsing ---

def test_get_text():
    content = [{"text": "hello "}, {"text": "world"}]
    assert get_text(content) == "hello world"


def test_get_text_with_tool_blocks():
    content = [
        {"text": "thinking..."},
        {"toolUse": {"toolUseId": "1", "name": "bash", "input": {}}},
    ]
    assert get_text(content) == "thinking..."


def test_get_tool_uses():
    content = [
        {"text": "let me check"},
        {"toolUse": {"toolUseId": "abc", "name": "bash", "input": {"command": "ls"}}},
        {"toolUse": {"toolUseId": "def", "name": "read_file", "input": {"path": "x.py"}}},
    ]
    tools = get_tool_uses(content)
    assert len(tools) == 2
    assert tools[0]["name"] == "bash"
    assert tools[1]["input"]["path"] == "x.py"


# --- Tool format conversion ---

def test_to_bedrock_tools():
    tools = [{"name": "bash", "description": "Run cmd.", "input_schema": {"type": "object"}}]
    result = to_bedrock_tools(tools)
    assert len(result) == 1
    spec = result[0]["toolSpec"]
    assert spec["name"] == "bash"
    assert spec["inputSchema"]["json"] == {"type": "object"}


# --- Clean content ---

def test_clean_content_strips_empty_text():
    content = [{"text": ""}, {"toolUse": {"toolUseId": "1", "name": "bash", "input": {}}}]
    cleaned = _clean_content(content)
    assert len(cleaned) == 1
    assert "toolUse" in cleaned[0]


def test_clean_content_preserves_nonempty():
    content = [{"text": "hello"}, {"text": "world"}]
    cleaned = _clean_content(content)
    assert len(cleaned) == 2


def test_clean_content_all_empty_returns_placeholder():
    content = [{"text": ""}]
    cleaned = _clean_content(content)
    assert cleaned == [{"text": "(empty)"}]


# --- Batch converse ---

def test_converse_batch(mock_client):
    """converse() returns parsed message and stop reason."""
    mock_client.converse.return_value = make_converse_response(
        text="Hello!", stop_reason="end_turn"
    )
    msg, stop, usage = converse(mock_client, "test-model", "system", [user_msg("hi")])
    assert msg["role"] == "assistant"
    assert get_text(msg["content"]) == "Hello!"
    assert stop == "end_turn"
    assert usage["inputTokens"] == 100
    assert usage["outputTokens"] == 50


def test_converse_with_tool_use(mock_client):
    """converse() handles tool_use responses."""
    mock_client.converse.return_value = make_converse_response(
        tool_uses=[{"toolUseId": "t1", "name": "bash", "input": {"command": "ls"}}],
        stop_reason="tool_use",
    )
    msg, stop, usage = converse(mock_client, "test-model", "", [user_msg("list files")])
    assert stop == "tool_use"
    tools = get_tool_uses(msg["content"])
    assert len(tools) == 1
    assert tools[0]["name"] == "bash"


# --- Streaming converse ---

def test_converse_stream_text_only(mock_client, capsys):
    """converse_stream() streams text and assembles the message."""
    events = make_stream_events(text="Hello, I can help!", stop_reason="end_turn")
    mock_client.converse_stream.return_value = {"stream": iter(events)}

    msg, stop, usage = converse_stream(mock_client, "test-model", "", [user_msg("hi")])

    assert stop == "end_turn"
    assert msg["role"] == "assistant"
    assert get_text(msg["content"]) == "Hello, I can help!"
    assert usage["inputTokens"] == 100
    assert usage["outputTokens"] == 50

    # Verify text was printed to stdout
    captured = capsys.readouterr()
    assert "Hello, I can help!" in captured.out


def test_converse_stream_tool_use(mock_client, capsys):
    """converse_stream() accumulates tool_use blocks."""
    events = make_stream_events(
        text="Let me check.",
        tool_uses=[{"toolUseId": "t1", "name": "bash", "input": {"command": "ls"}}],
        stop_reason="tool_use",
    )
    mock_client.converse_stream.return_value = {"stream": iter(events)}

    msg, stop, usage = converse_stream(mock_client, "test-model", "", [user_msg("list")])

    assert stop == "tool_use"
    assert get_text(msg["content"]) == "Let me check."
    tools = get_tool_uses(msg["content"])
    assert len(tools) == 1
    assert tools[0]["name"] == "bash"
    assert tools[0]["input"]["command"] == "ls"


def test_converse_stream_tool_only(mock_client, capsys):
    """converse_stream() works with tool_use and no text."""
    events = make_stream_events(
        tool_uses=[{"toolUseId": "t1", "name": "read_file", "input": {"path": "x.py"}}],
        stop_reason="tool_use",
    )
    mock_client.converse_stream.return_value = {"stream": iter(events)}

    msg, stop, usage = converse_stream(mock_client, "test-model", "", [user_msg("read")])

    assert stop == "tool_use"
    tools = get_tool_uses(msg["content"])
    assert len(tools) == 1
    assert tools[0]["input"]["path"] == "x.py"

    # No text should have been printed
    captured = capsys.readouterr()
    assert captured.out.strip() == ""


def test_converse_stream_multiple_tools(mock_client, capsys):
    """converse_stream() handles multiple tool calls."""
    events = make_stream_events(
        tool_uses=[
            {"toolUseId": "t1", "name": "bash", "input": {"command": "ls"}},
            {"toolUseId": "t2", "name": "read_file", "input": {"path": "a.py"}},
        ],
        stop_reason="tool_use",
    )
    mock_client.converse_stream.return_value = {"stream": iter(events)}

    msg, stop, usage = converse_stream(mock_client, "test-model", "", [user_msg("do stuff")])
    tools = get_tool_uses(msg["content"])
    assert len(tools) == 2
    assert tools[0]["name"] == "bash"
    assert tools[1]["name"] == "read_file"
