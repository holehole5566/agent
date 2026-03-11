"""Workspace — document-based persistent memory with hybrid search.

Provides a filesystem-like API backed by PostgreSQL + pgvector.
Documents are chunked and indexed for full-text + semantic search.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from config import CFG
from _bedrock import get_client
from embeddings import get_embedding
from chunker import chunk_document, ChunkConfig

log = logging.getLogger("workspace")

# Well-known paths
MEMORY_PATH = "MEMORY.md"
DAILY_DIR = "daily"


def _today_path() -> str:
    return f"{DAILY_DIR}/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(fts_results: list, vector_results: list,
                           k: int = 60, limit: int = 5) -> list:
    """Combine FTS and vector results using RRF scoring."""
    scores = {}

    for rank, r in enumerate(fts_results, 1):
        cid = r["chunk_id"]
        scores[cid] = {**r, "score": 1.0 / (k + rank), "fts_rank": rank, "vector_rank": None}

    for rank, r in enumerate(vector_results, 1):
        cid = r["chunk_id"]
        if cid in scores:
            scores[cid]["score"] += 1.0 / (k + rank)
            scores[cid]["vector_rank"] = rank
        else:
            scores[cid] = {**r, "score": 1.0 / (k + rank), "fts_rank": None, "vector_rank": rank}

    results = sorted(scores.values(), key=lambda x: x["score"], reverse=True)

    # Normalize to 0-1
    if results:
        max_score = results[0]["score"]
        if max_score > 0:
            for r in results:
                r["score"] = r["score"] / max_score

    return results[:limit]


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class Workspace:
    """Document-based memory workspace backed by PostgreSQL + pgvector."""

    def __init__(self):
        self.enabled = CFG.memory.enabled
        self.conn = None
        self.client = None
        self.dimensions = CFG.memory.embedding_dimensions

        if not self.enabled:
            log.info("workspace disabled")
            return

        try:
            self.client = get_client()
            self.conn = psycopg2.connect(
                host=CFG.database.host,
                port=CFG.database.port,
                user=CFG.database.user,
                password=CFG.database.password,
                dbname=CFG.database.dbname,
            )
            self.conn.autocommit = True
            self._ensure_schema()
            log.info("workspace enabled (model: %s, dims: %d)",
                     CFG.memory.embedding_model, self.dimensions)
        except Exception as e:
            log.error("workspace init failed: %s", e)
            self.enabled = False

    def _ensure_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_documents (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    path TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    CONSTRAINT unique_path_per_user UNIQUE (user_id, path)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES memory_documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
                    embedding vector(%s),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT unique_chunk_per_doc UNIQUE (document_id, chunk_index)
                )
            """, (self.dimensions,))
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_tsv
                ON memory_chunks USING GIN(content_tsv)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_document
                ON memory_chunks(document_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_documents_path
                ON memory_documents(user_id, path)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_documents_updated
                ON memory_documents(updated_at DESC)
            """)
        log.info("workspace schema ready")

    # ==================== Document CRUD ====================

    def read(self, path: str, user_id: str = "default") -> dict | None:
        """Read a document by path. Returns dict with id, path, content, updated_at or None."""
        if not self.enabled:
            return None
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, path, content, created_at, updated_at FROM memory_documents "
                "WHERE user_id = %s AND path = %s",
                (user_id, path),
            )
            row = cur.fetchone()
            if row:
                return {k: (str(v) if isinstance(v, datetime) else v) for k, v in row.items()}
            return None

    def write(self, path: str, content: str, user_id: str = "default") -> dict:
        """Create or overwrite a document. Re-indexes chunks."""
        if not self.enabled:
            return {"error": "workspace disabled"}
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO memory_documents (user_id, path, content, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (user_id, path)
                DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
                RETURNING id
            """, (user_id, path, content))
            doc_id = cur.fetchone()[0]

        self._reindex(doc_id, content)
        log.debug("wrote %s (%d chars)", path, len(content))
        return {"path": path, "doc_id": doc_id, "content_length": len(content)}

    def append(self, path: str, content: str, user_id: str = "default") -> dict:
        """Append to a document (create if missing). Re-indexes chunks."""
        if not self.enabled:
            return {"error": "workspace disabled"}
        existing = self.read(path, user_id)
        if existing and existing["content"]:
            new_content = existing["content"] + "\n" + content
        else:
            new_content = content
        return self.write(path, new_content, user_id)

    def delete(self, path: str, user_id: str = "default") -> bool:
        """Delete a document and its chunks. Returns True if deleted."""
        if not self.enabled:
            return False
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM memory_documents WHERE user_id = %s AND path = %s",
                (user_id, path),
            )
            return cur.rowcount > 0

    def list_dir(self, directory: str = "", user_id: str = "default") -> list[dict]:
        """List immediate children of a directory path."""
        if not self.enabled:
            return []
        prefix = (directory.strip("/") + "/") if directory.strip("/") else ""

        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if prefix:
                cur.execute(
                    "SELECT path, updated_at, LEFT(content, 200) as preview "
                    "FROM memory_documents WHERE user_id = %s AND path LIKE %s "
                    "ORDER BY path",
                    (user_id, prefix + "%"),
                )
            else:
                cur.execute(
                    "SELECT path, updated_at, LEFT(content, 200) as preview "
                    "FROM memory_documents WHERE user_id = %s ORDER BY path",
                    (user_id,),
                )
            rows = cur.fetchall()

        # Group into immediate children
        entries = {}
        for row in rows:
            rel = row["path"][len(prefix):] if prefix else row["path"]
            if "/" in rel:
                child = rel.split("/")[0] + "/"
                if child not in entries:
                    entries[child] = {"path": prefix + child, "is_directory": True}
            else:
                entries[rel] = {
                    "path": row["path"],
                    "is_directory": False,
                    "updated_at": str(row["updated_at"]),
                    "preview": row["preview"],
                }
        return list(entries.values())

    # ==================== Convenience ====================

    def read_memory(self, user_id: str = "default") -> str:
        """Read MEMORY.md content (for system prompt injection)."""
        doc = self.read(MEMORY_PATH, user_id)
        return doc["content"] if doc else ""

    def append_memory(self, content: str, user_id: str = "default") -> dict:
        """Append to MEMORY.md with double newline separation."""
        existing = self.read(MEMORY_PATH, user_id)
        if existing and existing["content"]:
            new_content = existing["content"] + "\n\n" + content
        else:
            new_content = content
        return self.write(MEMORY_PATH, new_content, user_id)

    def append_daily_log(self, content: str, user_id: str = "default") -> dict:
        """Append timestamped entry to today's daily log."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{timestamp}] {content}"
        return self.append(_today_path(), entry, user_id)

    # ==================== Indexing ====================

    def _reindex(self, doc_id: int, content: str):
        """Delete old chunks, re-chunk, embed, and insert."""
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM memory_chunks WHERE document_id = %s", (doc_id,))

        chunks = chunk_document(content)
        if not chunks:
            return

        for i, chunk_text in enumerate(chunks):
            embedding = self._embed(chunk_text)
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory_chunks (document_id, chunk_index, content, embedding) "
                    "VALUES (%s, %s, %s, %s)",
                    (doc_id, i, chunk_text, str(embedding) if embedding else None),
                )

    def _embed(self, text: str) -> list | None:
        """Generate embedding vector. Returns None on failure."""
        if not self.client:
            return None
        try:
            return get_embedding(self.client, text)
        except Exception as e:
            log.warning("embedding failed: %s", e)
            return None

    # ==================== Hybrid Search ====================

    def search(self, query: str, limit: int = 5, user_id: str = "default") -> list[dict]:
        """Hybrid search: FTS + vector similarity, fused with RRF."""
        if not self.enabled:
            return []

        pre_limit = limit * 5  # fetch extra for fusion
        fts_results = self._search_fts(query, pre_limit, user_id)
        vector_results = self._search_vector(query, pre_limit, user_id)

        if not fts_results and not vector_results:
            return []

        return reciprocal_rank_fusion(fts_results, vector_results, k=60, limit=limit)

    def _search_fts(self, query: str, limit: int, user_id: str) -> list[dict]:
        """Full-text search using tsvector."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.id AS chunk_id, c.document_id, d.path, c.content,
                           ts_rank_cd(c.content_tsv, plainto_tsquery('english', %s)) AS rank
                    FROM memory_chunks c
                    JOIN memory_documents d ON d.id = c.document_id
                    WHERE c.content_tsv @@ plainto_tsquery('english', %s)
                      AND d.user_id = %s
                    ORDER BY rank DESC
                    LIMIT %s
                """, (query, query, user_id, limit))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            log.warning("FTS search failed: %s", e)
            return []

    def _search_vector(self, query: str, limit: int, user_id: str) -> list[dict]:
        """Vector cosine similarity search."""
        embedding = self._embed(query)
        if not embedding:
            return []
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.id AS chunk_id, c.document_id, d.path, c.content,
                           1 - (c.embedding <=> %s) AS similarity
                    FROM memory_chunks c
                    JOIN memory_documents d ON d.id = c.document_id
                    WHERE c.embedding IS NOT NULL
                      AND d.user_id = %s
                    ORDER BY c.embedding <=> %s
                    LIMIT %s
                """, (str(embedding), user_id, str(embedding), limit))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            log.warning("vector search failed: %s", e)
            return []

    # ==================== Stats ====================

    def stats(self, user_id: str = "default") -> dict:
        """Get workspace statistics."""
        if not self.enabled:
            return {"enabled": False}
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memory_documents WHERE user_id = %s", (user_id,))
            doc_count = cur.fetchone()[0]
            cur.execute("""
                SELECT COUNT(*) FROM memory_chunks c
                JOIN memory_documents d ON d.id = c.document_id
                WHERE d.user_id = %s
            """, (user_id,))
            chunk_count = cur.fetchone()[0]
        return {"documents": doc_count, "chunks": chunk_count}

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
