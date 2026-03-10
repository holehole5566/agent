"""
Shared helpers for AWS Bedrock Converse API.

Bedrock Converse vs Anthropic SDK key differences:
  - client.converse() instead of client.messages.create()
  - system=[{"text": ...}] instead of system="..."
  - tools wrapped in {"toolSpec": {..., "inputSchema": {"json": ...}}}
  - content is always a list of blocks: [{"text": ...}] or [{"toolUse": ...}]
  - tool results: [{"toolResult": {"toolUseId": ..., "content": [{"text": ...}]}}]
  - response['stopReason'] instead of response.stop_reason
  - response['output']['message'] is the assistant message dict
"""

import json
import logging

import boto3

from config import CFG

log = logging.getLogger("bedrock")


def get_client():
    """Create a Bedrock Runtime client."""
    return boto3.client(
        "bedrock-runtime",
        region_name=CFG.model.region,
    )


def get_model():
    """Get the model ID from config."""
    return CFG.model.model_id


# -- Message helpers --

def user_msg(text: str) -> dict:
    """Build a user message from a plain string."""
    return {"role": "user", "content": [{"text": text or "(empty)"}]}


def asst_msg(text: str) -> dict:
    """Build an assistant message from a plain string."""
    return {"role": "assistant", "content": [{"text": text or "(empty)"}]}


# -- Tool format conversion --

def to_bedrock_tools(tools: list) -> list:
    """Convert Anthropic-style tool defs to Bedrock Converse format.

    Input:  [{"name": "bash", "description": "...", "input_schema": {...}}]
    Output: [{"toolSpec": {"name": "bash", "description": "...", "inputSchema": {"json": {...}}}}]
    """
    return [
        {
            "toolSpec": {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": {"json": t["input_schema"]},
            }
        }
        for t in tools
    ]


def _build_kwargs(model, system, messages, tools, max_tokens):
    kwargs = {
        "modelId": model,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system:
        kwargs["system"] = [{"text": system}]
    if tools:
        kwargs["toolConfig"] = {"tools": tools}
    return kwargs


def _clean_content(content: list) -> list:
    """Strip empty text blocks that Bedrock sometimes returns alongside toolUse."""
    cleaned = [
        block for block in content
        if not ("text" in block and not block["text"])
    ]
    return cleaned if cleaned else [{"text": "(empty)"}]


# -- Converse wrapper (batch) --

def converse(client, model: str, system: str, messages: list,
             tools: list = None, max_tokens: int = 4096) -> tuple:
    """Call Bedrock Converse API (batch, no streaming).

    Returns: (assistant_message_dict, stop_reason)
    """
    kwargs = _build_kwargs(model, system, messages, tools, max_tokens)
    response = client.converse(**kwargs)
    msg = response["output"]["message"]
    msg["content"] = _clean_content(msg["content"])
    usage = response.get("usage", {})
    return msg, response["stopReason"], usage


# -- Converse wrapper (streaming) --

def converse_stream(client, model: str, system: str, messages: list,
                    tools: list = None, max_tokens: int = 4096) -> tuple:
    """Call Bedrock Converse API with streaming.

    Prints text tokens to stdout as they arrive.
    Returns: (assistant_message_dict, stop_reason) — same shape as converse().
    """
    kwargs = _build_kwargs(model, system, messages, tools, max_tokens)
    response = client.converse_stream(**kwargs)

    content_blocks = []
    current_text = None
    current_tool = None
    stop_reason = "end_turn"
    has_streamed_text = False
    usage = {}
    import sys
    safe_print = lambda s: sys.stdout.buffer.write(s.encode("utf-8", errors="replace")) and sys.stdout.buffer.flush()

    for event in response["stream"]:
        if "contentBlockStart" in event:
            start = event["contentBlockStart"]
            start_data = start.get("start", {})
            if "toolUse" in start_data:
                current_tool = {
                    "toolUseId": start_data["toolUse"]["toolUseId"],
                    "name": start_data["toolUse"]["name"],
                    "input_json": "",
                }
                current_text = None
            else:
                current_text = ""
                current_tool = None

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                if current_text is None:
                    current_text = ""
                chunk = delta["text"]
                current_text += chunk
                safe_print(chunk)
                has_streamed_text = True
            elif "toolUse" in delta:
                if current_tool is not None:
                    current_tool["input_json"] += delta["toolUse"].get("input", "")

        elif "contentBlockStop" in event:
            if current_text is not None:
                if current_text:
                    content_blocks.append({"text": current_text})
                current_text = None
            elif current_tool is not None:
                try:
                    parsed = json.loads(current_tool["input_json"]) if current_tool["input_json"] else {}
                except json.JSONDecodeError:
                    log.warning("failed to parse tool input JSON for %s", current_tool["name"])
                    parsed = {}
                content_blocks.append({
                    "toolUse": {
                        "toolUseId": current_tool["toolUseId"],
                        "name": current_tool["name"],
                        "input": parsed,
                    }
                })
                current_tool = None

        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason", "end_turn")

        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})

    if has_streamed_text:
        safe_print("\n")  # newline after streamed text

    content_blocks = _clean_content(content_blocks) if content_blocks else [{"text": "(empty)"}]

    msg = {"role": "assistant", "content": content_blocks}
    return msg, stop_reason, usage


# -- Response parsing helpers --

def get_text(content: list) -> str:
    """Extract all text from content blocks."""
    return "".join(block["text"] for block in content if "text" in block)


def get_tool_uses(content: list) -> list:
    """Extract toolUse dicts from content blocks.

    Returns: [{"toolUseId": ..., "name": ..., "input": {...}}, ...]
    """
    return [block["toolUse"] for block in content if "toolUse" in block]


def make_tool_results(results: list) -> list:
    """Build content blocks for tool results.

    Input:  [{"toolUseId": "abc", "content": "output text"}, ...]
    Output: [{"toolResult": {"toolUseId": "abc", "content": [{"text": "output text"}]}}, ...]
    """
    return [
        {
            "toolResult": {
                "toolUseId": r["toolUseId"],
                "content": [{"text": str(r["content"])}],
            }
        }
        for r in results
    ]
