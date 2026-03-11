"""Tests for memory system (embeddings, vector store, memory manager)."""

import json
from unittest.mock import MagicMock, patch

from embeddings import get_embedding
from memory import MemoryManager


def test_get_embedding(mock_client):
    """Embedding provider returns a vector from Bedrock Titan."""
    mock_client.invoke_model.return_value = {
        "body": MagicMock(read=lambda: json.dumps({
            "embedding": [0.1, 0.2, 0.3] * 341 + [0.1]  # 1024 dims
        }).encode())
    }
    result = get_embedding(mock_client, "hello world")
    assert len(result) == 1024
    assert isinstance(result[0], float)


def test_get_embedding_truncates_long_text(mock_client):
    """Embedding provider truncates text longer than 8000 chars."""
    mock_client.invoke_model.return_value = {
        "body": MagicMock(read=lambda: json.dumps({
            "embedding": [0.0] * 1024
        }).encode())
    }
    long_text = "x" * 20000
    get_embedding(mock_client, long_text)

    # Check the body sent to Bedrock
    call_args = mock_client.invoke_model.call_args
    body = json.loads(call_args[1]["body"])
    assert len(body["inputText"]) == 8000


def test_memory_manager_disabled():
    """When memory is disabled, all operations return gracefully."""
    with patch("memory.CFG") as mock_cfg:
        mock_cfg.memory.enabled = False
        mm = MemoryManager()
        assert mm.enabled is False
        assert mm.recall("anything") == []
        assert mm.build_context("anything") == ""
        assert mm.remember("test") == "Memory is disabled."
        assert mm.stats() == "Memory is disabled."


def test_memory_manager_save_exchange_disabled():
    """save_exchange returns None when disabled."""
    with patch("memory.CFG") as mock_cfg:
        mock_cfg.memory.enabled = False
        mm = MemoryManager()
        assert mm.save_exchange("hello", "hi") is None


def test_memory_build_context_format():
    """build_context returns formatted memory block."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.enabled = True
    mm.client = MagicMock()
    mm.store = MagicMock()

    # Mock recall to return test memories
    mm.store.search.return_value = [
        {"content": "User prefers Python", "memory_type": "note",
         "created_at": "2025-01-15", "similarity": 0.9, "score": 0.85,
         "id": 1, "session_id": None, "metadata": {}},
        {"content": "Project uses FastAPI", "memory_type": "conversation",
         "created_at": "2025-01-10", "similarity": 0.8, "score": 0.7,
         "id": 2, "session_id": None, "metadata": {}},
    ]
    mm.client.invoke_model.return_value = {
        "body": MagicMock(read=lambda: json.dumps({"embedding": [0.0] * 1024}).encode())
    }

    ctx = mm.build_context("what language do we use?")
    assert "<memories>" in ctx
    assert "</memories>" in ctx
    assert "User prefers Python" in ctx
    assert "Project uses FastAPI" in ctx


def test_memory_build_context_budget():
    """build_context respects character budget."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.enabled = True
    mm.client = MagicMock()
    mm.store = MagicMock()

    mm.store.search.return_value = [
        {"content": "A" * 3000, "memory_type": "note",
         "created_at": "2025-01-15", "similarity": 0.9, "score": 0.9,
         "id": 1, "session_id": None, "metadata": {}},
        {"content": "B" * 3000, "memory_type": "note",
         "created_at": "2025-01-14", "similarity": 0.8, "score": 0.8,
         "id": 2, "session_id": None, "metadata": {}},
    ]
    mm.client.invoke_model.return_value = {
        "body": MagicMock(read=lambda: json.dumps({"embedding": [0.0] * 1024}).encode())
    }

    ctx = mm.build_context("test", budget_chars=4000)
    # Should only include the first memory (3000+ chars), not both
    assert "A" * 100 in ctx
    assert "B" * 100 not in ctx


def test_memory_remember_and_forget():
    """remember saves, forget deletes."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.enabled = True
    mm.client = MagicMock()
    mm.store = MagicMock()
    mm.store.store.return_value = 42

    mm.client.invoke_model.return_value = {
        "body": MagicMock(read=lambda: json.dumps({"embedding": [0.0] * 1024}).encode())
    }

    result = mm.remember("important fact")
    assert "42" in result
    mm.store.store.assert_called_once()

    result = mm.forget(42)
    assert "42" in result
    mm.store.delete.assert_called_once_with(42)


def test_memory_stats():
    """stats returns counts."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.enabled = True
    mm.store = MagicMock()
    mm.store.count.side_effect = [100, 80, 20]  # total, convos, notes

    result = mm.stats()
    assert "100" in result
    assert "80" in result
    assert "20" in result
