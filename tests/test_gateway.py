"""Tests for gateway and channel routing."""

import json
from unittest.mock import MagicMock, patch

from channels.base import Channel
from gateway import Gateway, Session
from dm_policy import DMPolicy
from _bedrock import user_msg
from conftest import make_stream_events


class FakeChannel(Channel):
    """Test channel that records all calls."""

    def __init__(self, gateway):
        super().__init__(gateway)
        self.sent = []
        self.chunks = []
        self.done_calls = []

    @property
    def name(self):
        return "test"

    def start(self):
        pass

    def stop(self):
        pass

    def send_response(self, user_id, text):
        self.sent.append((user_id, text))

    def on_text_chunk(self, user_id, chunk):
        self.chunks.append((user_id, chunk))

    def on_response_done(self, user_id, full_text):
        self.done_calls.append((user_id, full_text))


def test_gateway_registers_channel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    gw = Gateway()
    ch = FakeChannel(gw)
    gw.register_channel("test", ch)
    assert "test" in gw.channels


def test_gateway_creates_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    gw = Gateway()
    session = gw._get_session("cli", "user1")
    assert session.channel_name == "cli"
    assert session.user_id == "user1"

    # Same key returns same session
    session2 = gw._get_session("cli", "user1")
    assert session is session2


def test_gateway_different_channels_different_sessions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    gw = Gateway()
    s1 = gw._get_session("cli", "user1")
    s2 = gw._get_session("telegram", "user1")
    assert s1 is not s2


def test_gateway_routes_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    import agent
    events = make_stream_events(text="Hello from agent!", stop_reason="end_turn")
    mock_client = MagicMock()
    mock_client.converse_stream.return_value = {"stream": iter(events)}
    monkeypatch.setattr(agent, "client", mock_client)

    gw = Gateway()
    gw.dm_policy = DMPolicy(mode="open")
    ch = FakeChannel(gw)
    gw.register_channel("test", ch)

    gw.handle_message(ch, "user1", "hi")

    # Channel should have received chunks and done call
    assert len(ch.chunks) > 0
    assert len(ch.done_calls) == 1
    assert "Hello from agent!" in ch.done_calls[0][1]


def test_gateway_dm_policy_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    gw = Gateway()
    gw.dm_policy = DMPolicy(mode="allowlist", allowlist=["vip"])
    ch = FakeChannel(gw)
    gw.register_channel("test", ch)

    gw.handle_message(ch, "random_user", "hi")

    # Should be blocked — sent rejection, no agent call
    assert len(ch.sent) == 1
    assert "allowlist" in ch.sent[0][1].lower()
    assert len(ch.done_calls) == 0


def test_gateway_dm_policy_pairing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for d in [".tasks", ".team", ".team/inbox", ".sessions", "skills", ".transcripts"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "test"\n')

    import dm_policy as dm_mod
    monkeypatch.setattr(dm_mod, "ALLOWLIST_FILE", tmp_path / "allowlist.json")

    gw = Gateway()
    gw.dm_policy = DMPolicy(mode="pairing", pairing_code="abc123")
    ch = FakeChannel(gw)
    gw.register_channel("test", ch)

    # First message without code — rejected
    gw.handle_message(ch, "user1", "hello")
    assert len(ch.sent) >= 1
    assert "pairing code" in ch.sent[0][1].lower()

    # Send pairing code — paired
    gw.handle_message(ch, "user1", "abc123")
    paired_msgs = [s for s in ch.sent if "Paired" in s[1]]
    assert len(paired_msgs) == 1
