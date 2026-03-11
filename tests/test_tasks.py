"""Tests for task manager (PostgreSQL-backed)."""

import json
from unittest.mock import MagicMock, patch

from tasks import TaskManager


def _make_manager():
    """Create a TaskManager with mocked DB connection."""
    with patch("tasks.psycopg2") as mock_pg:
        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.autocommit = True
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        tm = TaskManager()
    return tm, mock_conn, mock_cursor


def _mock_row(tid=1, subject="Test task", description="", status="pending",
              owner=None, blocked_by=None, blocks=None):
    return {
        "id": tid, "subject": subject, "description": description,
        "status": status, "owner": owner,
        "blocked_by": blocked_by or [], "blocks": blocks or [],
    }


def test_create_task():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _mock_row(1, "Build login page", "Add OAuth")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = json.loads(tm.create("Build login page", "Add OAuth"))
    assert result["subject"] == "Build login page"
    assert result["status"] == "pending"
    assert result["id"] == 1


def test_get_task():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _mock_row(1, "My task")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = json.loads(tm.get(1))
    assert result["subject"] == "My task"


def test_get_nonexistent():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    try:
        tm.get(999)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not found" in str(e)


def test_update_status():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _mock_row(1, "My task", status="in_progress")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = json.loads(tm.update(1, status="in_progress"))
    assert result["status"] == "in_progress"


def test_delete_task():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    # First call returns the task (for _load), second call is the DELETE
    mock_cursor.fetchone.return_value = _mock_row(1, "Deletable")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = tm.update(1, status="deleted")
    assert "deleted" in result.lower()
    delete_calls = [c for c in mock_cursor.execute.call_args_list if "DELETE" in str(c)]
    assert len(delete_calls) >= 1


def test_claim_task():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _mock_row(1, "Claimable", owner=None)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = tm.claim(1, "alice")
    assert "Claimed" in result
    update_calls = [c for c in mock_cursor.execute.call_args_list if "UPDATE" in str(c)]
    assert len(update_calls) >= 1


def test_claim_already_claimed():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = _mock_row(1, "Claimed", owner="alice")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = tm.claim(1, "bob")
    assert "Error" in result
    assert "alice" in result


def test_claim_nonexistent():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = tm.claim(999, "alice")
    assert "Error" in result


def test_list_all_empty():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = tm.list_all()
    assert "No tasks" in result


def test_list_all():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        _mock_row(1, "Task A"),
        _mock_row(2, "Task B", status="in_progress", owner="alice"),
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = tm.list_all()
    assert "Task A" in result
    assert "Task B" in result
    assert "@alice" in result


def test_list_unclaimed():
    tm, mock_conn, _ = _make_manager()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        _mock_row(1, "Unclaimed task"),
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    result = tm.list_unclaimed()
    assert len(result) == 1
    assert result[0]["subject"] == "Unclaimed task"


def test_disabled_graceful():
    with patch("tasks.psycopg2") as mock_pg:
        mock_pg.connect.side_effect = Exception("connection refused")
        tm = TaskManager()

    assert tm._enabled is False
    assert "not available" in tm.create("test").lower() or "error" in tm.create("test").lower()
    assert tm.list_all() == "Task store not available."
    assert tm.list_unclaimed() == []
