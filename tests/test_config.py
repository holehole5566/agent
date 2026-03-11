"""Tests for config loading."""

import tomllib
from pathlib import Path

from config import Config, ModelConfig, AgentConfig, load_config


def test_load_from_toml(tmp_path, monkeypatch):
    """Config loads values from config.toml."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[model]\nmodel_id = "my-custom-model"\nregion = "ap-northeast-1"\nmax_tokens = 4000\n'
        '[agent]\ntoken_threshold = 50000\n'
        '[team]\npoll_interval = 10\nidle_timeout = 120\n'
    )
    cfg = load_config()
    assert cfg.model.model_id == "my-custom-model"
    assert cfg.model.region == "ap-northeast-1"
    assert cfg.model.max_tokens == 4000
    assert cfg.agent.token_threshold == 50000
    assert cfg.team.poll_interval == 10
    assert cfg.team.idle_timeout == 120


def test_defaults_without_toml(tmp_path, monkeypatch):
    """Config falls back to defaults when no config.toml exists."""
    monkeypatch.chdir(tmp_path)
    # Remove any .env that might interfere
    monkeypatch.delenv("MODEL_ID", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    cfg = load_config()
    assert cfg.model.model_id == "us.anthropic.claude-sonnet-4-6"
    assert cfg.model.region == "us-east-1"
    assert cfg.agent.token_threshold == 100000


def test_partial_toml_uses_defaults(tmp_path, monkeypatch):
    """Config fills in defaults for missing sections."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text('[model]\nmodel_id = "partial-model"\n')
    cfg = load_config()
    assert cfg.model.model_id == "partial-model"
    assert cfg.model.region == "us-east-1"  # default
    assert cfg.agent.token_threshold == 100000  # default
    assert cfg.paths.team_dir == ".team"  # default


def test_paths_config(tmp_path, monkeypatch):
    """Custom paths from config.toml are respected."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[paths]\nteam_dir = "my-team"\nskills_dir = "my-skills"\n'
    )
    cfg = load_config()
    assert cfg.paths.team_dir == "my-team"
    assert cfg.paths.skills_dir == "my-skills"
