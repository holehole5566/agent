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
class GatewayConfig:
    channels: list = field(default_factory=lambda: ["cli"])


@dataclass
class TelegramConfig:
    token: str = ""
    owner_id: str = ""


@dataclass
class DMPolicyConfig:
    mode: str = "open"
    allowlist: list = field(default_factory=list)
    pairing_code: str = ""


@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    user: str = ""
    password: str = ""
    dbname: str = "agent"


@dataclass
class MemoryConfig:
    enabled: bool = False
    embedding_model: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: int = 1024
    max_results: int = 5


@dataclass
class RoutinesConfig:
    enabled: bool = True
    check_interval: int = 15


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    dm_policy: DMPolicyConfig = field(default_factory=DMPolicyConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    routines: RoutinesConfig = field(default_factory=RoutinesConfig)


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
            gateway=GatewayConfig(**data.get("gateway", {})),
            telegram=TelegramConfig(**data.get("telegram", {})),
            dm_policy=DMPolicyConfig(**data.get("dm_policy", {})),
            database=DatabaseConfig(**data.get("database", {})),
            memory=MemoryConfig(**data.get("memory", {})),
            routines=RoutinesConfig(**data.get("routines", {})),
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
