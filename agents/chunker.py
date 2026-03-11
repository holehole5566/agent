"""Document chunking for search indexing.

Documents are split into overlapping chunks for better search recall.
"""

from dataclasses import dataclass


@dataclass
class ChunkConfig:
    chunk_size: int = 800       # target words per chunk
    overlap_percent: float = 0.15
    min_chunk_size: int = 50    # don't create tiny trailing chunks

    @property
    def overlap_size(self) -> int:
        return int(self.chunk_size * self.overlap_percent)

    @property
    def step_size(self) -> int:
        return max(1, self.chunk_size - self.overlap_size)


def chunk_document(content: str, config: ChunkConfig | None = None) -> list[str]:
    """Split document into overlapping word-based chunks."""
    if not content or not content.strip():
        return []

    config = config or ChunkConfig()
    words = content.split()

    if not words:
        return []

    if len(words) <= config.chunk_size:
        return [content]

    chunks = []
    start = 0

    while start < len(words):
        end = min(start + config.chunk_size, len(words))
        chunk_words = words[start:end]

        # Merge tiny trailing chunk with previous
        if len(chunk_words) < config.min_chunk_size and chunks:
            chunks[-1] = chunks[-1] + " " + " ".join(chunk_words)
            break

        chunks.append(" ".join(chunk_words))
        start += config.step_size

        # Avoid duplicate chunk at the end
        if start + config.min_chunk_size >= len(words) and end == len(words):
            break

    return chunks
