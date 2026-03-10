"""Shared fixtures for all tests."""

import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_workdir(tmp_path, monkeypatch):
    """Set up a temporary working directory with all agent subdirs."""
    monkeypatch.chdir(tmp_path)

    # Create subdirs that the agent expects
    for d in [".tasks", ".team", ".team/inbox", ".transcripts", ".sessions", "skills"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    # Write a minimal config.toml
    (tmp_path / "config.toml").write_text(
        '[model]\nmodel_id = "test-model"\nregion = "us-east-1"\n'
        '[paths]\ntasks_dir = ".tasks"\nteam_dir = ".team"\n'
        'sessions_dir = ".sessions"\nskills_dir = "skills"\n'
        'transcripts_dir = ".transcripts"\n'
    )

    return tmp_path


@pytest.fixture
def mock_client():
    """A mock Bedrock client that returns configurable responses."""
    client = MagicMock()
    return client


def make_assistant_msg(text=None, tool_uses=None):
    """Helper to build an assistant message dict."""
    content = []
    if text:
        content.append({"text": text})
    if tool_uses:
        for tu in tool_uses:
            content.append({"toolUse": tu})
    return {"role": "assistant", "content": content}


def make_converse_response(text=None, tool_uses=None, stop_reason="end_turn"):
    """Helper to build a Bedrock converse() API response."""
    msg = make_assistant_msg(text, tool_uses)
    return {
        "output": {"message": msg},
        "stopReason": stop_reason,
        "usage": {"inputTokens": 100, "outputTokens": 50},
    }


def make_stream_events(text=None, tool_uses=None, stop_reason="end_turn"):
    """Build a list of streaming events that mimic converse_stream() output."""
    events = [{"messageStart": {"role": "assistant"}}]
    block_idx = 0

    if text:
        # Bedrock skips contentBlockStart for text blocks — goes straight to deltas
        for i in range(0, len(text), 10):
            chunk = text[i:i + 10]
            events.append({
                "contentBlockDelta": {
                    "contentBlockIndex": block_idx,
                    "delta": {"text": chunk},
                }
            })
        events.append({"contentBlockStop": {"contentBlockIndex": block_idx}})
        block_idx += 1

    if tool_uses:
        for tu in tool_uses:
            events.append({
                "contentBlockStart": {
                    "contentBlockIndex": block_idx,
                    "start": {"toolUse": {"toolUseId": tu["toolUseId"], "name": tu["name"]}},
                }
            })
            input_json = json.dumps(tu["input"])
            events.append({
                "contentBlockDelta": {
                    "contentBlockIndex": block_idx,
                    "delta": {"toolUse": {"input": input_json}},
                }
            })
            events.append({"contentBlockStop": {"contentBlockIndex": block_idx}})
            block_idx += 1

    events.append({"messageStop": {"stopReason": stop_reason}})
    events.append({"metadata": {"usage": {"inputTokens": 100, "outputTokens": 50}}})
    return events
