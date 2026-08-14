"""Tests for upscaler_cli.config.CLIConfig profile-aware behavior."""

import json

from upscaler_cli.config import _DEFAULT_SERVER_URL, _STG_SERVER_URL, CLIConfig


def test_default_profile_uses_build_time_default(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    config = CLIConfig()
    assert config.profile == "prod"
    assert config.resolve_server_url() == _DEFAULT_SERVER_URL


def test_dev_profile_defaults_to_staging(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    config = CLIConfig(profile="dev")
    assert config.resolve_server_url() == _STG_SERVER_URL


def test_custom_profile_falls_back_to_build_default(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    config = CLIConfig(profile="custom")
    assert config.resolve_server_url() == _DEFAULT_SERVER_URL


def test_profile_config_is_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))

    prod = CLIConfig(profile="prod")
    dev = CLIConfig(profile="dev")
    prod.set("server_url", "https://prod.example")
    dev.set("server_url", "https://dev.example")

    # Re-open to bypass in-memory caches.
    assert CLIConfig(profile="prod").resolve_server_url() == "https://prod.example"
    assert CLIConfig(profile="dev").resolve_server_url() == "https://dev.example"


def test_flag_beats_env_beats_config(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    config = CLIConfig(profile="prod")
    config.set("server_url", "https://config.example")

    monkeypatch.setenv("UPSCALER_SERVER", "https://env.example")
    assert config.resolve_server_url() == "https://env.example"
    assert config.resolve_server_url("https://flag.example") == "https://flag.example"


def test_config_persists_to_profile_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    config = CLIConfig(profile="dev")
    config.set("server_url", "https://stg.example")
    saved = json.loads(
        (tmp_path / "home" / "profiles" / "dev" / "config.json").read_text()
    )
    assert saved["server_url"] == "https://stg.example"
