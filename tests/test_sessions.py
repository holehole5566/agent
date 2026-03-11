"""Tests for session persistence (PostgreSQL-backed)."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

from sessions import SessionManager


def _make_manager():
    """Create a SessionManager with mocked DB connection."""
    with patch("sessions.psycopg2") as mock_pg:
        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.autocommit = True
        # Mock cursor context manager
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        sm = SessionManager()
    return sm, mock_conn, mock_cursor


def test_make_id():
    assert SessionManager._make_id("telegram", "123") == "telegram:123"
    assert SessionManager._make_id("cli", "user1") == "cli:user1"


def test_extract_preview():
    messages = [
        {"role": "user", "content": [{"text": "Tell me about Python"}]},
        {"role": "assistant", "content": [{"text": "Python is..."}]},
    ]
    assert "Python" in SessionManager._extract_preview(messages)


def test_extract_preview_empty():
    assert SessionManager._extract_preview([]) == ""
    assert SessionManager._extract_preview([{"role": "assistant", "content": []}]) == ""


def test_get_or_create_new():
    """New session returns empty history and inserts row."""
    sm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None  # no existing session
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    sid, history = sm.get_or_create("telegram", "123")
    assert sid == "telegram:123"
    assert history == []
    # Should have called INSERT
    insert_call = [c for c in mock_cursor.execute.call_args_list if "INSERT" in str(c)]
    assert len(insert_call) == 1


def test_get_or_create_existing():
    """Existing session returns stored history."""
    sm, mock_conn, _ = _make_manager()
    stored_messages = [{"role": "user", "content": [{"text": "hello"}]}]
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"messages": stored_messages}
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    sid, history = sm.get_or_create("telegram", "123")
    assert sid == "telegram:123"
    assert history == stored_messages


def test_save():
    """Save updates the session row."""
    sm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    messages = [
        {"role": "user", "content": [{"text": "hello"}]},
        {"role": "assistant", "content": [{"text": "hi"}]},
    ]
    sm.save("telegram:123", messages)

    update_call = [c for c in mock_cursor.execute.call_args_list if "UPDATE" in str(c)]
    assert len(update_call) == 1


def test_save_empty_noop():
    """Save with empty messages does nothing."""
    sm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    sm.save("telegram:123", [])
    assert mock_cursor.execute.call_count == 0


def test_load_existing():
    """Load returns messages for existing session."""
    sm, mock_conn, _ = _make_manager()
    stored = [{"role": "user", "content": [{"text": "test"}]}]
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"messages": stored}
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = sm.load("telegram:123")
    assert result == stored


def test_load_nonexistent_raises():
    """Loading a nonexistent session raises ValueError."""
    sm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    try:
        sm.load("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not found" in str(e)


def test_list_sessions_empty():
    """List returns message when no sessions exist."""
    sm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = sm.list_sessions()
    assert "No saved sessions" in result


def test_list_sessions():
    """List formats session rows correctly."""
    sm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {
            "id": "telegram:123",
            "channel": "telegram",
            "user_id": "123",
            "preview": "hello world",
            "updated_at": datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc),
        },
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = sm.list_sessions()
    assert "telegram:123" in result
    assert "hello world" in result
    assert "2026-03-11" in result


def test_disabled_graceful():
    """When DB connection fails, all ops are graceful."""
    with patch("sessions.psycopg2") as mock_pg:
        mock_pg.connect.side_effect = Exception("connection refused")
        sm = SessionManager()

    assert sm._enabled is False
    sid, history = sm.get_or_create("telegram", "123")
    assert sid == "telegram:123"
    assert history == []
    # save should not raise
    sm.save("telegram:123", [{"role": "user", "content": [{"text": "hi"}]}])
    assert sm.list_sessions() == "Session store not available."
