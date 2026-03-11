# CLAUDE.md

## Project Overview

A lightweight coding agent built on AWS Bedrock Converse API. Multi-channel (CLI, Telegram), with tool system, permissions, hooks, sessions, multi-agent teams, and vector memory.

## Tech Stack

- Python 3.11+, managed with `uv`
- AWS Bedrock (Claude models via Converse API)
- PostgreSQL + pgvector for vector memory
- boto3, psycopg2-binary, python-dotenv

## Project Structure

- `main.py` — entry point, starts gateway + channels
- `agents/` — core modules (agent loop, config, tools, permissions, sessions, etc.)
- `agents/channels/` — channel implementations (CLI, Telegram)
- `hooks/` — auto-loaded `.py` hook files (lifecycle events)
- `skills/` — YAML frontmatter + markdown skill files
- `tests/` — pytest test suite
- `config.toml` — runtime config (gitignored); see `config.toml.example`

## Key Commands

```bash
# Run the agent
uv run python main.py

# Run tests
uv run pytest tests/ -v

# Install dependencies
uv sync
```

## Code Conventions

- Config is loaded via `agents/config.py` using dataclasses + TOML
- All imports in `main.py` use `sys.path` insertion for `agents/`; tests use `pythonpath = ["agents"]` in pyproject.toml
- Tools are defined in `agents/agent.py` and executed via `agents/tools.py`
- Permissions use scope-based model: read/write/execute/admin/agent
- Hook functions follow `on_<event>` naming convention
- No type annotations beyond dataclasses; keep code simple and direct

## Testing

- pytest with `pythonpath = ["agents"]` so test imports match agent internals
- Tests live in `tests/` and cover agent loop, config, tools, permissions, hooks, sessions, gateway, DM policy, scanner, memory, bedrock
