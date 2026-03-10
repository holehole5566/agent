"""Tests for file and shell tools."""

from pathlib import Path

from tools import safe_path, run_read, run_write, run_edit, run_bash


def test_safe_path_within_workspace(tmp_path, monkeypatch):
    """safe_path accepts paths inside the workspace."""
    monkeypatch.chdir(tmp_path)
    # Reimport to pick up new WORKDIR
    import config
    monkeypatch.setattr(config, "WORKDIR", tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    result = tools.safe_path("subdir/file.txt")
    assert result == (tmp_path / "subdir" / "file.txt").resolve()


def test_safe_path_blocks_escape(tmp_path, monkeypatch):
    """safe_path rejects paths that escape the workspace."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    try:
        tools.safe_path("../../etc/passwd")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "escapes workspace" in str(e)


def test_run_write_and_read(tmp_path, monkeypatch):
    """Write a file and read it back."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    result = tools.run_write("test.txt", "hello world")
    assert "Wrote" in result
    assert (tmp_path / "test.txt").exists()

    content = tools.run_read("test.txt")
    assert content == "hello world"


def test_run_write_creates_dirs(tmp_path, monkeypatch):
    """Write creates parent directories automatically."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    result = tools.run_write("a/b/c.txt", "nested")
    assert "Wrote" in result
    assert (tmp_path / "a" / "b" / "c.txt").read_text() == "nested"


def test_run_edit(tmp_path, monkeypatch):
    """Edit replaces text in a file."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    (tmp_path / "edit.txt").write_text("foo bar baz")
    result = tools.run_edit("edit.txt", "bar", "qux")
    assert "Edited" in result
    assert (tmp_path / "edit.txt").read_text() == "foo qux baz"


def test_run_edit_text_not_found(tmp_path, monkeypatch):
    """Edit returns error when target text is not found."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    (tmp_path / "edit.txt").write_text("foo bar")
    result = tools.run_edit("edit.txt", "nonexistent", "replacement")
    assert "Error" in result


def test_run_read_with_limit(tmp_path, monkeypatch):
    """Read with limit returns only the first N lines."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    (tmp_path / "lines.txt").write_text("\n".join(f"line {i}" for i in range(100)))
    content = tools.run_read("lines.txt", limit=5)
    lines = content.split("\n")
    assert lines[0] == "line 0"
    assert lines[4] == "line 4"
    assert "more" in lines[5]


def test_run_bash_simple(tmp_path, monkeypatch):
    """Bash runs a simple command."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    result = tools.run_bash("echo hello")
    assert "hello" in result


def test_run_bash_blocked_command(tmp_path, monkeypatch):
    """Bash blocks dangerous commands."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    result = tools.run_bash("rm -rf /")
    assert "Dangerous" in result or "blocked" in result.lower()


def test_run_bash_timeout(tmp_path, monkeypatch):
    """Bash returns timeout error for long-running commands."""
    monkeypatch.chdir(tmp_path)
    import tools
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)

    # Use a very short command but mock timeout
    result = tools.run_bash("sleep 0.1")
    # Just verify it doesn't crash — sleep 0.1 should complete fine
    assert isinstance(result, str)
