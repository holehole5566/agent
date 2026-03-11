"""Tests for workspace system (chunker, RRF, workspace manager)."""

import json
from unittest.mock import MagicMock, patch, PropertyMock

from chunker import chunk_document, ChunkConfig
from workspace import reciprocal_rank_fusion, Workspace


# ==================== Chunker Tests ====================

class TestChunker:
    def test_empty_content(self):
        assert chunk_document("") == []
        assert chunk_document("   ") == []

    def test_small_content(self):
        content = "Hello world, this is a test."
        chunks = chunk_document(content)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_exact_chunk_size(self):
        config = ChunkConfig(chunk_size=5)
        content = "one two three four five"
        chunks = chunk_document(content, config)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_chunking_with_overlap(self):
        config = ChunkConfig(chunk_size=10, overlap_percent=0.2, min_chunk_size=3)
        words = " ".join(f"word{i}" for i in range(20))
        chunks = chunk_document(words, config)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk.split()) >= 3

    def test_overlap_calculation(self):
        config = ChunkConfig(chunk_size=100, overlap_percent=0.15)
        assert config.overlap_size == 15
        assert config.step_size == 85

    def test_min_chunk_merging(self):
        config = ChunkConfig(chunk_size=10, overlap_percent=0.0, min_chunk_size=5)
        words = " ".join(f"w{i}" for i in range(12))
        chunks = chunk_document(words, config)
        # Trailing 2 words should merge with previous chunk
        assert len(chunks) == 1
        assert len(chunks[0].split()) == 12


# ==================== RRF Tests ====================

class TestRRF:
    def test_single_method(self):
        fts = [
            {"chunk_id": 1, "document_id": 10, "path": "a.md", "content": "hello"},
            {"chunk_id": 2, "document_id": 10, "path": "a.md", "content": "world"},
        ]
        results = reciprocal_rank_fusion(fts, [], k=60, limit=10)
        assert len(results) == 2
        assert results[0]["score"] > results[1]["score"]
        assert all(r["fts_rank"] is not None for r in results)
        assert all(r["vector_rank"] is None for r in results)

    def test_hybrid_boost(self):
        shared = {"chunk_id": 1, "document_id": 10, "path": "a.md", "content": "shared"}
        fts_only = {"chunk_id": 2, "document_id": 10, "path": "a.md", "content": "fts"}
        vec_only = {"chunk_id": 3, "document_id": 10, "path": "a.md", "content": "vec"}

        fts = [shared.copy(), fts_only.copy()]
        vec = [shared.copy(), vec_only.copy()]

        results = reciprocal_rank_fusion(fts, vec, k=60, limit=10)
        assert len(results) == 3
        # Shared chunk should be first (boosted by appearing in both)
        assert results[0]["chunk_id"] == 1
        assert results[0]["fts_rank"] is not None
        assert results[0]["vector_rank"] is not None

    def test_score_normalization(self):
        fts = [{"chunk_id": 1, "document_id": 10, "path": "a.md", "content": "x"}]
        results = reciprocal_rank_fusion(fts, [], k=60, limit=10)
        assert len(results) == 1
        assert abs(results[0]["score"] - 1.0) < 0.001

    def test_limit(self):
        fts = [{"chunk_id": i, "document_id": 10, "path": "a.md", "content": f"c{i}"}
               for i in range(10)]
        results = reciprocal_rank_fusion(fts, [], k=60, limit=3)
        assert len(results) == 3

    def test_both_empty(self):
        assert reciprocal_rank_fusion([], []) == []


# ==================== Workspace Tests ====================

class TestWorkspaceDisabled:
    def test_all_ops_graceful(self):
        with patch("workspace.CFG") as mock_cfg:
            mock_cfg.memory.enabled = False
            ws = Workspace()
            assert ws.enabled is False
            assert ws.read("anything") is None
            assert ws.search("anything") == []
            assert ws.list_dir() == []
            assert ws.read_memory() == ""
            assert ws.stats() == {"enabled": False}


class TestMemoryWriteRouting:
    """Test the memory_write routing logic (mirrors _memory_write in agent.py)."""

    @staticmethod
    def _memory_write(ws, content, target="daily_log", append=True):
        """Replicate the routing logic from agent._memory_write."""
        from workspace import MEMORY_PATH
        if target == "memory":
            if append:
                return ws.append_memory(content)
            return ws.write(MEMORY_PATH, content)
        elif target == "daily_log":
            return ws.append_daily_log(content)
        else:
            if append:
                return ws.append(target, content)
            return ws.write(target, content)

    def test_daily_log(self):
        ws = MagicMock()
        ws.append_daily_log.return_value = {"path": "daily/2026-03-11.md"}
        self._memory_write(ws, "test note", target="daily_log")
        ws.append_daily_log.assert_called_once_with("test note")

    def test_memory_append(self):
        ws = MagicMock()
        ws.append_memory.return_value = {"path": "MEMORY.md"}
        self._memory_write(ws, "important fact", target="memory", append=True)
        ws.append_memory.assert_called_once_with("important fact")

    def test_memory_overwrite(self):
        ws = MagicMock()
        ws.write.return_value = {"path": "MEMORY.md"}
        self._memory_write(ws, "new content", target="memory", append=False)
        ws.write.assert_called_once_with("MEMORY.md", "new content")

    def test_custom_path_append(self):
        ws = MagicMock()
        ws.append.return_value = {"path": "projects/notes.md"}
        self._memory_write(ws, "note", target="projects/notes.md", append=True)
        ws.append.assert_called_once_with("projects/notes.md", "note")

    def test_custom_path_overwrite(self):
        ws = MagicMock()
        ws.write.return_value = {"path": "projects/notes.md"}
        self._memory_write(ws, "note", target="projects/notes.md", append=False)
        ws.write.assert_called_once_with("projects/notes.md", "note")
