"""Shared configuration - loads from config.toml with env var fallback."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelConfig:
    provider: str = "bedrock"
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    region: str = "us-east-1"
    max_tokens: int = 8000


@dataclass
class AgentConfig:
    token_threshold: int = 100000


@dataclass
class TeamConfig:
    poll_interval: int = 5
    idle_timeout: int = 60


@dataclass
class PathsConfig:
    skills_dir: str = "skills"
    tasks_dir: str = ".tasks"
    team_dir: str = ".team"
    transcripts_dir: str = ".transcripts"
    sessions_dir: str = ".sessions"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = ""


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config() -> Config:
    config_path = Path.cwd() / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return Config(
            model=ModelConfig(**data.get("model", {})),
            agent=AgentConfig(**data.get("agent", {})),
            team=TeamConfig(**data.get("team", {})),
            paths=PathsConfig(**data.get("paths", {})),
            logging=LoggingConfig(**data.get("logging", {})),
        )
    # Fallback: env vars (backward compat with .env)
    from dotenv import load_dotenv
    load_dotenv(override=True)
    return Config(
        model=ModelConfig(
            model_id=os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
            region=os.environ.get("AWS_REGION", "us-east-1"),
        )
    )


CFG = load_config()

# Backward-compatible exports
WORKDIR = Path.cwd()
TEAM_DIR = WORKDIR / CFG.paths.team_dir
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = WORKDIR / CFG.paths.tasks_dir
SKILLS_DIR = WORKDIR / CFG.paths.skills_dir
TRANSCRIPT_DIR = WORKDIR / CFG.paths.transcripts_dir
SESSIONS_DIR = WORKDIR / CFG.paths.sessions_dir

TOKEN_THRESHOLD = CFG.agent.token_threshold
POLL_INTERVAL = CFG.team.poll_interval
IDLE_TIMEOUT = CFG.team.idle_timeout

VALID_MSG_TYPES = {
    "message", "broadcast", "shutdown_request",
    "shutdown_response", "plan_approval_response",
}
