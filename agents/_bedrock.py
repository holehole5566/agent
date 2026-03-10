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

import os

import boto3
from dotenv import load_dotenv

load_dotenv(override=True)


def get_client():
    """Create a Bedrock Runtime client."""
    return boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


def get_model():
    """Get the model ID from environment."""
    return os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")


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


# -- Converse wrapper --

def converse(client, model: str, system: str, messages: list,
             tools: list = None, max_tokens: int = 4096) -> tuple:
    """Call Bedrock Converse API.

    Returns: (assistant_message_dict, stop_reason)
        assistant_message_dict = {"role": "assistant", "content": [...]}
        stop_reason = "end_turn" | "tool_use" | "max_tokens" | ...
    """
    kwargs = {
        "modelId": model,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system:
        kwargs["system"] = [{"text": system}]
    if tools:
        kwargs["toolConfig"] = {"tools": tools}
    response = client.converse(**kwargs)
    msg = response["output"]["message"]
    # Bedrock can return empty text blocks alongside toolUse blocks;
    # strip them so they don't cause ValidationException on the next call
    msg["content"] = [
        block for block in msg["content"]
        if not ("text" in block and not block["text"])
    ]
    if not msg["content"]:
        msg["content"] = [{"text": "(empty)"}]
    return msg, response["stopReason"]


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
