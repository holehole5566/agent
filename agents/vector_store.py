"""Vector store backed by PostgreSQL + pgvector."""

import json
import logging
import time

import psycopg2
import psycopg2.extras

from config import CFG

log = logging.getLogger("vector_store")


class VectorStore:
    """PostgreSQL + pgvector backed memory store."""

    def __init__(self):
        self.conn = None
        self.dimensions = CFG.memory.embedding_dimensions

    def connect(self):
        """Connect to PostgreSQL and ensure schema exists."""
        self.conn = psycopg2.connect(
            host=CFG.database.host,
            port=CFG.database.port,
            user=CFG.database.user,
            password=CFG.database.password,
            dbname=CFG.database.dbname,
        )
        self.conn.autocommit = True
        self._ensure_schema()
        log.info("connected to PostgreSQL at %s/%s", CFG.database.host, CFG.database.dbname)

    def _ensure_schema(self):
        """Create pgvector extension and tables if they don't exist."""
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS memories (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    embedding vector({self.dimensions}),
                    created_at TIMESTAMP DEFAULT NOW(),
                    session_id TEXT,
                    memory_type TEXT DEFAULT 'conversation'
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_embedding
                ON memories USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 10)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_type
                ON memories (memory_type)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_created
                ON memories (created_at DESC)
            """)
        log.info("schema ready")

    def store(self, content: str, embedding: list, metadata: dict = None,
              session_id: str = None, memory_type: str = "conversation"):
        """Store a memory with its embedding vector."""
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO memories (content, embedding, metadata, session_id, memory_type)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (content, str(embedding), json.dumps(metadata or {}), session_id, memory_type),
            )
            mid = cur.fetchone()[0]
        log.debug("stored memory #%d (%s, %d chars)", mid, memory_type, len(content))
        return mid

    def search(self, query_embedding: list, limit: int = None,
               memory_type: str = None, decay_days: float = 30.0) -> list:
        """Semantic search with optional temporal decay and type filter.

        Returns list of dicts: [{id, content, metadata, similarity, created_at}, ...]
        """
        limit = limit or CFG.memory.max_results

        # Build query with cosine similarity + temporal decay
        type_filter = "AND memory_type = %s" if memory_type else ""
        query = f"""
            SELECT id, content, metadata, created_at, session_id, memory_type,
                   1 - (embedding <=> %s) AS similarity,
                   EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0 AS age_days
            FROM memories
            WHERE embedding IS NOT NULL
            {type_filter}
            ORDER BY embedding <=> %s
            LIMIT %s
        """

        params = [str(query_embedding)]
        if memory_type:
            params.append(memory_type)
        params.extend([str(query_embedding), limit * 2])  # fetch extra for reranking

        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        # Apply temporal decay and MMR-like deduplication
        results = []
        seen_content = set()
        for row in rows:
            # Temporal decay: reduce score for older memories
            age = float(row["age_days"])
            decay = 1.0 / (1.0 + age / decay_days)
            score = float(row["similarity"]) * decay

            # Simple dedup: skip near-identical content
            content_key = row["content"][:100]
            if content_key in seen_content:
                continue
            seen_content.add(content_key)

            results.append({
                "id": row["id"],
                "content": row["content"],
                "metadata": row["metadata"],
                "similarity": float(row["similarity"]),
                "score": score,
                "created_at": str(row["created_at"]),
                "session_id": row["session_id"],
                "memory_type": row["memory_type"],
            })

        # Sort by decayed score and return top results
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def delete(self, memory_id: int):
        """Delete a memory by ID."""
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM memories WHERE id = %s", (memory_id,))

    def count(self, memory_type: str = None) -> int:
        """Count stored memories."""
        with self.conn.cursor() as cur:
            if memory_type:
                cur.execute("SELECT COUNT(*) FROM memories WHERE memory_type = %s", (memory_type,))
            else:
                cur.execute("SELECT COUNT(*) FROM memories")
            return cur.fetchone()[0]

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
