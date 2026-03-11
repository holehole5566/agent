"""Memory manager — orchestrates embedding, storage, search, and context injection."""

import logging

from config import CFG
from _bedrock import get_client, get_text
from embeddings import get_embedding
from vector_store import VectorStore

log = logging.getLogger("memory")


class MemoryManager:
    """High-level memory API for the agent."""

    def __init__(self):
        self.enabled = CFG.memory.enabled
        self.store = None
        self.client = None
        if not self.enabled:
            log.info("memory disabled")
            return
        try:
            self.client = get_client()
            self.store = VectorStore()
            self.store.connect()
            log.info("memory enabled (%d dimensions, model: %s)",
                     CFG.memory.embedding_dimensions, CFG.memory.embedding_model)
        except Exception as e:
            log.error("memory init failed: %s", e)
            self.enabled = False

    def save(self, content: str, session_id: str = None,
             memory_type: str = "conversation", metadata: dict = None) -> int | None:
        """Save a text to memory with its embedding."""
        if not self.enabled or not content.strip():
            return None
        try:
            embedding = get_embedding(self.client, content)
            return self.store.store(content, embedding, metadata, session_id, memory_type)
        except Exception as e:
            log.error("memory save failed: %s", e)
            return None

    def save_exchange(self, user_text: str, agent_text: str,
                      session_id: str = None) -> int | None:
        """Save a user/agent exchange as a single memory."""
        if not self.enabled:
            return None
        combined = f"User: {user_text}\nAgent: {agent_text}"
        return self.save(combined, session_id, "conversation")

    def recall(self, query: str, limit: int = None,
               memory_type: str = None) -> list:
        """Search memories semantically. Returns list of memory dicts."""
        if not self.enabled:
            return []
        try:
            embedding = get_embedding(self.client, query)
            return self.store.search(embedding, limit, memory_type)
        except Exception as e:
            log.error("memory recall failed: %s", e)
            return []

    def build_context(self, query: str, budget_chars: int = 4000) -> str:
        """Build a context string from relevant memories, fitting within budget."""
        if not self.enabled:
            return ""
        memories = self.recall(query)
        if not memories:
            return ""
        lines = []
        total = 0
        for mem in memories:
            entry = f"[{mem['memory_type']}|{mem['created_at'][:10]}] {mem['content']}"
            if total + len(entry) > budget_chars:
                break
            lines.append(entry)
            total += len(entry)
        if not lines:
            return ""
        return "<memories>\n" + "\n---\n".join(lines) + "\n</memories>"

    def remember(self, content: str, session_id: str = None) -> str:
        """Explicitly save a fact/note. Returns confirmation."""
        if not self.enabled:
            return "Memory is disabled."
        mid = self.save(content, session_id, "note")
        if mid:
            return f"Remembered (memory #{mid})."
        return "Failed to save memory."

    def forget(self, memory_id: int) -> str:
        """Delete a specific memory."""
        if not self.enabled:
            return "Memory is disabled."
        try:
            self.store.delete(memory_id)
            return f"Forgot memory #{memory_id}."
        except Exception as e:
            return f"Error: {e}"

    def stats(self) -> str:
        """Get memory statistics."""
        if not self.enabled:
            return "Memory is disabled."
        try:
            total = self.store.count()
            convos = self.store.count("conversation")
            notes = self.store.count("note")
            return f"Memories: {total} total ({convos} conversations, {notes} notes)"
        except Exception as e:
            return f"Error: {e}"

    def close(self):
        if self.store:
            self.store.close()
