"""Embedding provider using AWS Bedrock Titan."""

import json
import logging

from config import CFG

log = logging.getLogger("embeddings")


def get_embedding(client, text: str) -> list:
    """Get embedding vector for a text string using Bedrock Titan.

    Returns a list of floats.
    """
    body = json.dumps({
        "inputText": text[:8000],  # Titan limit
        "dimensions": CFG.memory.embedding_dimensions,
    })
    response = client.invoke_model(
        modelId=CFG.memory.embedding_model,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result["embedding"]


def get_embeddings_batch(client, texts: list) -> list:
    """Get embeddings for multiple texts. Returns list of vectors."""
    return [get_embedding(client, t) for t in texts]
