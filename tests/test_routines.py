"""Tests for routines (cron-triggered tasks)."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from routines import RoutineManager, _next_cron_fire


def _make_manager():
    """Create a RoutineManager with mocked DB connection."""
    with patch("routines.psycopg2") as mock_pg:
        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.autocommit = True
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        rm = RoutineManager()
    return rm, mock_conn, mock_cursor


def _mock_routine_row(rid=1, name="test-routine", schedule="0 9 * * *",
                      prompt="do something", enabled=True, run_count=0):
    return {
        "id": rid, "name": name, "description": "",
        "schedule": schedule, "prompt": prompt,
        "enabled": enabled, "cooldown_secs": 300,
        "next_fire_at": datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc),
        "last_run_at": None, "run_count": run_count,
    }


class TestNextCronFire:
    def test_valid_cron(self):
        after = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
        result = _next_cron_fire("0 9 * * *", after)
        assert result is not None
        assert result.hour == 9
        assert result.day == 12  # next day

    def test_invalid_cron(self):
        result = _next_cron_fire("invalid cron")
        assert result is None

    def test_every_minute(self):
        after = datetime(2026, 3, 11, 10, 30, tzinfo=timezone.utc)
        result = _next_cron_fire("* * * * *", after)
        assert result is not None
        assert result.minute == 31


class TestRoutineManager:
    def test_create(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = _mock_routine_row()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = json.loads(rm.create("test-routine", "0 9 * * *", "do something"))
        assert result["name"] == "test-routine"
        assert result["schedule"] == "0 9 * * *"

    def test_create_invalid_cron(self):
        rm, _, _ = _make_manager()
        result = json.loads(rm.create("bad", "not-a-cron", "prompt"))
        assert "error" in result

    def test_delete(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = rm.delete("test-routine")
        assert "Deleted" in result

    def test_delete_nonexistent(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = rm.delete("nope")
        assert "not found" in result

    def test_list_empty(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        assert "No routines" in rm.list_all()

    def test_list_all(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [_mock_routine_row()]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = rm.list_all()
        assert "test-routine" in result
        assert "0 9 * * *" in result

    def test_toggle(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = rm.toggle("test-routine", False)
        assert "disabled" in result

    def test_history_empty(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = rm.history("test-routine")
        assert "No runs" in result

    def test_history(self):
        rm, mock_conn, _ = _make_manager()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{
            "id": 1, "routine_id": 1,
            "started_at": datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 3, 11, 9, 1, tzinfo=timezone.utc),
            "status": "ok", "result_summary": "All good",
        }]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = rm.history("test-routine")
        assert "ok" in result
        assert "All good" in result

    def test_disabled_graceful(self):
        with patch("routines.psycopg2") as mock_pg:
            mock_pg.connect.side_effect = Exception("connection refused")
            rm = RoutineManager()

        assert rm._enabled is False
        assert "not available" in rm.list_all().lower()
        assert rm.get_due_routines() == []
