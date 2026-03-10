"""Conversation compression utilities."""

import json
import time

from config import TRANSCRIPT_DIR, TOKEN_THRESHOLD
from _bedrock import converse, get_text, user_msg, asst_msg


def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4


def microcompact(messages: list):
    tool_results = []
    for msg in messages:
        if msg["role"] == "user":
            for block in msg.get("content", []):
                if isinstance(block, dict) and "toolResult" in block:
                    tool_results.append(block)
    if len(tool_results) <= 3:
        return
    for tr in tool_results[:-3]:
        inner = tr["toolResult"].get("content", [])
        if inner and isinstance(inner[0], dict) and len(inner[0].get("text", "")) > 100:
            inner[0]["text"] = "[cleared]"


def auto_compact(messages: list, client, model: str) -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    conv_text = json.dumps(messages, default=str)[:80000]
    summary_msg, _, _ = converse(client, model, "", [user_msg(f"Summarize for continuity:\n{conv_text}")], max_tokens=2000)
    summary = get_text(summary_msg["content"])
    return [user_msg(f"[Compressed. Transcript: {path}]\n{summary}"), asst_msg("Understood. Continuing with summary context.")]
