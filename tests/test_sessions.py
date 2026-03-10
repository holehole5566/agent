"""Tests for session persistence."""

import json

from sessions import SessionManager


def test_new_session(tmp_path, monkeypatch):
    """New session creates a unique ID."""
    monkeypatch.chdir(tmp_path)
    import config
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path / ".sessions")

    import sessions
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / ".sessions")

    sm = SessionManager()
    sid = sm.new_session()
    assert sid.startswith("s_")
    assert sm.current_id == sid


def test_save_and_load(tmp_path, monkeypatch):
    """Save messages and load them back."""
    monkeypatch.chdir(tmp_path)
    sessions_dir = tmp_path / ".sessions"

    import sessions
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)

    sm = SessionManager()
    sm.new_session()

    messages = [
        {"role": "user", "content": [{"text": "hello"}]},
        {"role": "assistant", "content": [{"text": "hi there"}]},
    ]
    sm.save(messages)

    # Verify file exists
    saved_file = sessions_dir / f"{sm.current_id}.json"
    assert saved_file.exists()

    # Load and verify
    loaded = sm.load(sm.current_id)
    assert len(loaded) == 2
    assert loaded[0]["role"] == "user"
    assert loaded[1]["content"][0]["text"] == "hi there"


def test_save_extracts_preview(tmp_path, monkeypatch):
    """Save stores a preview from the first user message."""
    sessions_dir = tmp_path / ".sessions"
    import sessions
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)

    sm = SessionManager()
    sm.new_session()
    messages = [
        {"role": "user", "content": [{"text": "Tell me about Python decorators"}]},
        {"role": "assistant", "content": [{"text": "Decorators are..."}]},
    ]
    sm.save(messages)

    data = json.loads((sessions_dir / f"{sm.current_id}.json").read_text())
    assert "Python decorators" in data["preview"]


def test_load_nonexistent_raises(tmp_path, monkeypatch):
    """Loading a nonexistent session raises ValueError."""
    sessions_dir = tmp_path / ".sessions"
    import sessions
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)

    sm = SessionManager()
    try:
        sm.load("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not found" in str(e)


def test_list_sessions(tmp_path, monkeypatch):
    """List shows saved sessions."""
    sessions_dir = tmp_path / ".sessions"
    import sessions
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)

    sm = SessionManager()
    assert "No saved sessions" in sm.list_sessions()

    sm.new_session()
    sm.save([{"role": "user", "content": [{"text": "test query"}]}])

    listing = sm.list_sessions()
    assert sm.current_id in listing
    assert "test query" in listing


def test_multiple_sessions(tmp_path, monkeypatch):
    """Multiple sessions can coexist."""
    sessions_dir = tmp_path / ".sessions"
    import sessions as sessions_mod
    monkeypatch.setattr(sessions_mod, "SESSIONS_DIR", sessions_dir)

    sm = SessionManager()

    # Use explicit IDs to avoid timestamp collision
    sm.current_id = "s_test_one"
    sm.save([{"role": "user", "content": [{"text": "session one"}]}])

    sm.current_id = "s_test_two"
    sm.save([{"role": "user", "content": [{"text": "session two"}]}])

    loaded1 = sm.load("s_test_one")
    assert loaded1[0]["content"][0]["text"] == "session one"

    loaded2 = sm.load("s_test_two")
    assert loaded2[0]["content"][0]["text"] == "session two"
