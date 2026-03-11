# Agent

A lightweight coding agent with essential features. Built on AWS Bedrock Converse API, designed to be simple, extensible, and multi-channel.

## Features

- **Streaming responses** — real-time token output via Bedrock `converse_stream`
- **Multi-channel** — CLI and Telegram out of the box, extensible to any platform
- **Gateway architecture** — per-user session isolation, headless or interactive mode
- **Tool system** — bash, file read/write/edit, background tasks, subagents, team management
- **Scope-based permissions** — read/write/execute/admin/agent scopes per tool; teammates get filtered toolsets
- **Skill loader** — YAML frontmatter + markdown skills with security scanning
- **Hook system** — 9 lifecycle events, auto-loaded from `hooks/` directory
- **DM policy** — open, allowlist, or one-time pairing code with persistent allowlist
- **Session persistence** — auto-save/restore conversations across restarts
- **Multi-agent teams** — spawn teammates with scoped permissions, JSONL messaging, auto-claim tasks
- **Context compression** — 3-layer: microcompact, auto-compact at token threshold, manual `/compact`
- **TOML config** — structured configuration with dataclass validation, env var fallback

## Quick Start

```bash
# Clone and install
git clone https://github.com/holehole5566/agent.git
cd agent
uv sync

# Configure
cp config.toml.example config.toml
# Edit config.toml — set your model_id, region, and optionally telegram token

# Run (interactive CLI)
uv run python main.py
```

## Configuration

All settings are in `config.toml`. See `config.toml.example` for all options.

```toml
[model]
model_id = "us.anthropic.claude-sonnet-4-6"
region = "us-east-1"

[gateway]
channels = ["cli"]  # or ["telegram"] for headless, or ["cli", "telegram"] for both

[telegram]
token = ""  # from @BotFather

[dm_policy]
mode = "open"  # "open", "allowlist", "pairing"
```

AWS credentials are loaded from the standard chain (`~/.aws/credentials`, env vars, IAM role, SSO).

## Telegram Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Set `telegram.token` in `config.toml`
3. Set `gateway.channels = ["telegram"]`
4. Optionally set `dm_policy.mode = "pairing"` — a one-time code is printed on startup; send it to the bot to pair
5. Run `uv run python main.py`

## Project Structure

```
main.py                  # Entry point — starts gateway + channels
config.toml              # Configuration (gitignored)
config.toml.example      # Template for config
hooks/                   # Workspace hooks (auto-loaded .py files)
skills/                  # SKILL.md files for specialized knowledge
agents/
  agent.py               # Agent loop, tool dispatch, tool definitions
  gateway.py             # Session management, message routing
  config.py              # TOML config loader with dataclasses
  _bedrock.py            # Bedrock API: converse, converse_stream, helpers
  channels/
    base.py              # Channel abstract base class
    cli.py               # Interactive terminal channel
    telegram.py          # Telegram bot channel
  tools.py               # File ops, bash execution, path guards
  permissions.py         # Scope-based tool authorization
  scanner.py             # Skill security scanner
  hooks.py               # Event hook system
  dm_policy.py           # DM access control (open/allowlist/pairing)
  sessions.py            # Session save/restore
  tasks.py               # Persistent task board
  team.py                # Multi-agent teammate management
  todos.py               # In-memory todo tracking
  messaging.py           # JSONL message bus
  background.py          # Background command execution
  compression.py         # Context compression pipeline
  skills.py              # Skill loader with security scanning
  log.py                 # Logging setup
tests/                   # 105 tests (pytest)
```

## CLI Commands

When running with the CLI channel:

| Command | Description |
|---------|-------------|
| `/clear` | Clear terminal |
| `/compact` | Manually compress conversation |
| `/tasks` | List task board |
| `/team` | List teammates |
| `/team clear` | Remove all teammates |
| `/inbox` | Read lead inbox |
| `/sessions` | List saved sessions |
| `/resume <id>` | Resume a saved session |
| `/hooks` | List registered hooks |
| `q` / `exit` | Quit |

## Hooks

Drop a `.py` file in `hooks/` to extend the agent. Functions named `on_<event>` are auto-registered.

```python
# hooks/token_tracker.py
def on_llm_after_response(data):
    usage = data.get("usage", {})
    print(f"  tokens: {usage.get('inputTokens', 0)} in / {usage.get('outputTokens', 0)} out")
```

Events: `agent:bootstrap`, `session:start`, `session:end`, `message:received`, `message:sent`, `llm:before-request`, `llm:after-response`, `tool:before-execute`, `tool:after-execute`

## Tests

```bash
uv run pytest tests/ -v
```

## License

MIT
