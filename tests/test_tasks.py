"""Tests for task manager."""

import json
from pathlib import Path

from tasks import TaskManager


def test_create_task(tmp_path, monkeypatch):
    """Create a task and verify it's saved."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    result = tm.create("Build login page", "Add OAuth support")
    data = json.loads(result)
    assert data["subject"] == "Build login page"
    assert data["status"] == "pending"
    assert data["id"] == 1

    # Verify file on disk
    assert (tasks_dir / "task_1.json").exists()


def test_create_multiple_tasks(tmp_path, monkeypatch):
    """IDs auto-increment."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    t1 = json.loads(tm.create("Task 1"))
    t2 = json.loads(tm.create("Task 2"))
    t3 = json.loads(tm.create("Task 3"))
    assert t1["id"] == 1
    assert t2["id"] == 2
    assert t3["id"] == 3


def test_get_task(tmp_path, monkeypatch):
    """Get a task by ID."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    tm.create("My task")
    result = json.loads(tm.get(1))
    assert result["subject"] == "My task"


def test_update_task_status(tmp_path, monkeypatch):
    """Update task status."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    tm.create("My task")
    result = json.loads(tm.update(1, status="in_progress"))
    assert result["status"] == "in_progress"


def test_claim_task(tmp_path, monkeypatch):
    """Claim a task assigns owner and sets in_progress."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    tm.create("Claimable task")
    result = tm.claim(1, "alice")
    assert "Claimed" in result

    task = json.loads(tm.get(1))
    assert task["owner"] == "alice"
    assert task["status"] == "in_progress"


def test_claim_already_claimed(tmp_path, monkeypatch):
    """Cannot claim an already claimed task."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    tm.create("Contested task")
    tm.claim(1, "alice")
    result = tm.claim(1, "bob")
    assert "Error" in result
    assert "alice" in result


def test_claim_nonexistent(tmp_path, monkeypatch):
    """Claiming nonexistent task returns error."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    result = tm.claim(999, "alice")
    assert "Error" in result


def test_list_all(tmp_path, monkeypatch):
    """List shows all tasks."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    assert "No tasks" in tm.list_all()

    tm.create("Task A")
    tm.create("Task B")
    listing = tm.list_all()
    assert "Task A" in listing
    assert "Task B" in listing


def test_delete_task(tmp_path, monkeypatch):
    """Deleting a task removes the file."""
    tasks_dir = tmp_path / ".tasks"
    import config
    monkeypatch.setattr(config, "TASKS_DIR", tasks_dir)
    import tasks
    monkeypatch.setattr(tasks, "TASKS_DIR", tasks_dir)

    tm = TaskManager()
    tm.create("Deletable")
    assert (tasks_dir / "task_1.json").exists()

    tm.update(1, status="deleted")
    assert not (tasks_dir / "task_1.json").exists()
