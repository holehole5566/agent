"""Tests for the agent loop with mocked LLM."""

import json
from unittest.mock import patch, MagicMock

from _bedrock import user_msg, get_text
from conftest import make_stream_events


def test_agent_loop_simple_response(tmp_path, monkeypatch):
    """Agent loop handles a simple text response (no tool use)."""
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    # Must import after monkeypatching cwd
    import agent

    events = make_stream_events(text="Hello! How can I help?", stop_reason="end_turn")
    mock_client = MagicMock()
    mock_client.converse_stream.return_value = {"stream": iter(events)}
    monkeypatch.setattr(agent, "client", mock_client)

    messages = [user_msg("hi")]
    agent.agent_loop(messages)

    # Should have user msg + assistant msg
    assert len(messages) == 2
    assert messages[1]["role"] == "assistant"
    assert "Hello" in get_text(messages[1]["content"])


def test_agent_loop_tool_then_response(tmp_path, monkeypatch):
    """Agent loop dispatches a tool and then gets a final response."""
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    import agent

    # First call: agent wants to use bash
    tool_events = make_stream_events(
        tool_uses=[{"toolUseId": "t1", "name": "bash", "input": {"command": "echo test123"}}],
        stop_reason="tool_use",
    )
    # Second call: agent gives final response
    final_events = make_stream_events(text="Done! The output was test123.", stop_reason="end_turn")

    mock_client = MagicMock()
    mock_client.converse_stream.side_effect = [
        {"stream": iter(tool_events)},
        {"stream": iter(final_events)},
    ]
    monkeypatch.setattr(agent, "client", mock_client)

    messages = [user_msg("run echo test123")]
    agent.agent_loop(messages)

    # Messages: user, assistant(tool_use), user(tool_result), assistant(text)
    assert len(messages) == 4
    assert messages[1]["role"] == "assistant"  # tool call
    assert messages[2]["role"] == "user"  # tool result
    assert messages[3]["role"] == "assistant"  # final response

    # Check tool result was captured
    tool_result_content = messages[2]["content"]
    result_text = tool_result_content[0]["toolResult"]["content"][0]["text"]
    assert "test123" in result_text


def test_agent_loop_read_file_tool(tmp_path, monkeypatch):
    """Agent loop handles read_file tool."""
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')
    (tmp_path / "hello.txt").write_text("file content here")

    import agent
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    tool_events = make_stream_events(
        tool_uses=[{"toolUseId": "t1", "name": "read_file", "input": {"path": "hello.txt"}}],
        stop_reason="tool_use",
    )
    final_events = make_stream_events(text="The file says: file content here", stop_reason="end_turn")

    mock_client = MagicMock()
    mock_client.converse_stream.side_effect = [
        {"stream": iter(tool_events)},
        {"stream": iter(final_events)},
    ]
    monkeypatch.setattr(agent, "client", mock_client)

    messages = [user_msg("read hello.txt")]
    agent.agent_loop(messages)

    # Tool result should contain file content
    tool_result = messages[2]["content"][0]["toolResult"]["content"][0]["text"]
    assert "file content here" in tool_result


def test_agent_loop_write_file_tool(tmp_path, monkeypatch):
    """Agent loop handles write_file tool."""
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    import agent
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    tool_events = make_stream_events(
        tool_uses=[{"toolUseId": "t1", "name": "write_file", "input": {"path": "new.txt", "content": "created by agent"}}],
        stop_reason="tool_use",
    )
    final_events = make_stream_events(text="File created.", stop_reason="end_turn")

    mock_client = MagicMock()
    mock_client.converse_stream.side_effect = [
        {"stream": iter(tool_events)},
        {"stream": iter(final_events)},
    ]
    monkeypatch.setattr(agent, "client", mock_client)

    messages = [user_msg("create new.txt")]
    agent.agent_loop(messages)

    assert (tmp_path / "new.txt").read_text() == "created by agent"


def test_agent_loop_unknown_tool(tmp_path, monkeypatch):
    """Agent loop handles unknown tool gracefully."""
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    import agent

    tool_events = make_stream_events(
        tool_uses=[{"toolUseId": "t1", "name": "nonexistent_tool", "input": {}}],
        stop_reason="tool_use",
    )
    final_events = make_stream_events(text="Sorry about that.", stop_reason="end_turn")

    mock_client = MagicMock()
    mock_client.converse_stream.side_effect = [
        {"stream": iter(tool_events)},
        {"stream": iter(final_events)},
    ]
    monkeypatch.setattr(agent, "client", mock_client)

    messages = [user_msg("do something")]
    agent.agent_loop(messages)

    tool_result = messages[2]["content"][0]["toolResult"]["content"][0]["text"]
    assert "Unknown tool" in tool_result
