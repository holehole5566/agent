# Agent

An open-source AI agent framework with multi-channel support, persistent memory, and cron routines. Built on AWS Bedrock Converse API with PostgreSQL for durable state.

## Features

- **Multi-channel** — CLI and Telegram out of the box, extensible to any platform
- **Persistent sessions** — PostgreSQL-backed conversations that survive restarts
- **Workspace memory** — document-based memory with hybrid search (FTS + vector via pgvector)
- **Cron routines** — scheduled automated tasks with LLM execution and notifications
- **Task management** — persistent task board with dependencies and team assignment
- **Multi-agent teams** — spawn teammates with scoped permissions, messaging, auto-claim tasks
- **Streaming responses** — real-time token output via Bedrock `converse_stream`
- **Tool system** — bash, file read/write/edit, background tasks, subagents
- **Scope-based permissions** — read/write/execute/admin/agent scopes per teammate
- **Skill loader** — YAML frontmatter + markdown skills with security scanning
- **Hook system** — lifecycle events, auto-loaded from `hooks/` directory
- **Context compression** — microcompact, auto-compact at token threshold, manual `/compact`
- **CLI subcommands** — manage sessions, tasks, and routines without running the agent

## Quick Start

```bash
# Clone and install
git clone https://github.com/holehole5566/agent.git
cd agent
uv sync

# Configure
cp config.toml.example config.toml
# Edit config.toml — set your model, region, database, and optionally telegram token

# Run the agent
uv run python main.py
```

## CLI

```bash
# Serve (default)
uv run python main.py              # starts the agent
uv run python main.py serve        # explicit

# Subcommands (work independently, shared DB)
uv run python main.py sessions                    # list sessions
uv run python main.py sessions telegram:12345     # inspect a session
uv run python main.py tasks                       # list tasks
uv run python main.py routines                    # list routines
uv run python main.py routines create --name daily-check --schedule "0 9 * * *" --prompt "Check server status"
uv run python main.py routines history --name daily-check
uv run python main.py routines disable --name daily-check
uv run python main.py routines delete --name daily-check
```

## Configuration

All settings are in `config.toml`. See `config.toml.example` for all options.

```toml
[model]
model_id = "us.anthropic.claude-sonnet-4-6"
region = "us-east-1"

[database]
host = "localhost"
port = 5432
user = ""
password = ""
dbname = "agent"

[gateway]
channels = ["cli"]  # or ["telegram"] for headless, or ["cli", "telegram"] for both

[telegram]
token = ""         # from @BotFather
owner_id = ""      # restrict to your Telegram user ID

[memory]
enabled = true

[routines]
enabled = true
check_interval = 15
```

AWS credentials are loaded from the standard chain (`~/.aws/credentials`, env vars, IAM role, SSO).

## Telegram Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Set `telegram.token` in `config.toml`
3. Set `gateway.channels = ["telegram"]`
4. Set `telegram.owner_id` to your Telegram user ID to restrict access
5. Run `uv run python main.py`

Responses are sent with Markdown formatting (auto-fallback to plain text on parse errors).

## Project Structure

```
main.py                  # Entry point — serve or CLI subcommands
config.toml              # Configuration (gitignored)
config.toml.example      # Template
hooks/                   # Lifecycle hooks (auto-loaded .py files)
skills/                  # Markdown skill files
agents/
  agent.py               # Agent loop, tool dispatch, tool definitions
  gateway.py             # Session management, message routing
  config.py              # TOML config loader with dataclasses
  _bedrock.py            # Bedrock API: converse, converse_stream, helpers
  channels/
    base.py              # Channel abstract base class
    cli.py               # Interactive terminal channel
    telegram.py          # Telegram bot (owner_id, Markdown responses)
  sessions.py            # PostgreSQL session persistence
  tasks.py               # PostgreSQL task board
  routines.py            # Cron routines with LLM execution
  workspace.py           # Document memory with hybrid search
  chunker.py             # Text chunking for memory indexing
  embeddings.py          # Bedrock Titan embeddings
  tools.py               # File ops, bash execution, path guards
  permissions.py         # Scope-based tool authorization
  team.py                # Multi-agent teammate management
  messaging.py           # JSONL message bus
  background.py          # Background command execution
  compression.py         # Context compression pipeline
  skills.py              # Skill loader with security scanning
  hooks.py               # Event hook system
  dm_policy.py           # DM access control
  todos.py               # In-memory todo tracking
  log.py                 # Logging setup
tests/                   # 152 tests (pytest)
```

## Interactive Commands

When running with the CLI channel:

| Command | Description |
|---------|-------------|
| `/clear` | Clear terminal |
| `/compact` | Manually compress conversation |
| `/tasks` | List task board |
| `/team` | List teammates |
| `/team clear` | Remove all teammates |
| `/inbox` | Read lead inbox |
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
