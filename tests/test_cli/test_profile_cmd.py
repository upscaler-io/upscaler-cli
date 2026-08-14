"""Tests for `upscaler profile` command group."""

import json

import pytest
from click.testing import CliRunner

from upscaler_cli.auth.token_store import TokenData, TokenStore
from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_token():
    return TokenData(
        access_token="tok",
        refresh_token="ref",
        expires_at=9999999999.0,
        client_id="c",
        client_secret="s",
        organization_id="org_1",
        token_endpoint="https://example.com/token",
    )


def test_current_defaults_to_prod(runner):
    result = runner.invoke(cli, ["profile", "current"])
    assert result.exit_code == 0
    assert result.output.strip() == "prod"


def test_current_honors_flag(runner):
    result = runner.invoke(cli, ["--profile", "dev", "profile", "current"])
    assert result.exit_code == 0
    assert result.output.strip() == "dev"


def test_current_honors_env(runner, monkeypatch):
    monkeypatch.setenv("UPSCALER_PROFILE", "staging")
    result = runner.invoke(cli, ["profile", "current"])
    assert result.exit_code == 0
    assert result.output.strip() == "staging"


def test_list_shows_active_with_marker(runner, sample_token):
    # Authenticate the dev profile so we get an `auth` marker too.
    TokenStore(profile="dev").save(sample_token)

    result = runner.invoke(cli, ["--profile", "dev", "profile", "list"])
    assert result.exit_code == 0, result.output
    assert "* dev" in result.output
    assert "auth" in result.output


def test_list_json(runner, sample_token):
    TokenStore(profile="prod").save(sample_token)
    result = runner.invoke(cli, ["--json", "profile", "list"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["active"] == "prod"
    names = [p["name"] for p in payload["profiles"]]
    assert "prod" in names


def test_delete_refuses_prod(runner):
    result = runner.invoke(cli, ["profile", "delete", "prod"])
    assert result.exit_code == 1
    assert "default profile" in result.output


def test_delete_removes_profile(runner, sample_token):
    TokenStore(profile="dev").save(sample_token)
    result = runner.invoke(cli, ["profile", "delete", "dev", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Deleted profile 'dev'" in result.output

    follow_up = runner.invoke(cli, ["profile", "list"])
    assert "dev" not in follow_up.output


def test_delete_missing_profile_errors(runner):
    result = runner.invoke(cli, ["profile", "delete", "ghost", "--yes"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_invalid_profile_name_at_root_errors(runner):
    result = runner.invoke(cli, ["--profile", "../escape", "profile", "current"])
    assert result.exit_code == 1
    assert "Invalid profile name" in result.output


def test_path_prints_profile_dir(runner, tmp_path, monkeypatch):
    # UPSCALER_HOME is already pinned by the autouse fixture; just call.
    result = runner.invoke(cli, ["--profile", "dev", "profile", "path"])
    assert result.exit_code == 0
    assert "profiles/dev" in result.output


def test_isolated_auth_per_profile(runner, sample_token):
    TokenStore(profile="prod").save(sample_token)
    # dev should NOT report authenticated
    r1 = runner.invoke(cli, ["--profile", "prod", "status"])
    r2 = runner.invoke(cli, ["--profile", "dev", "status"])
    assert "Authenticated" in r1.output
    assert "Not authenticated" in r2.output


# ---- set-default ----


def test_set_default_changes_current(runner, sample_token):
    TokenStore(profile="dev").save(sample_token)

    result = runner.invoke(cli, ["profile", "set-default", "dev"])
    assert result.exit_code == 0, result.output
    assert "Default profile set to 'dev'" in result.output
    # No "has no data yet" note when the profile dir exists.
    assert "has no data yet" not in result.output

    follow_up = runner.invoke(cli, ["profile", "current"])
    assert follow_up.output.strip() == "dev"


def test_set_default_notes_unknown_profile(runner):
    result = runner.invoke(cli, ["profile", "set-default", "ghost"])
    assert result.exit_code == 0, result.output
    assert "has no data yet" in result.output


def test_set_default_json_output(runner):
    result = runner.invoke(cli, ["--json", "profile", "set-default", "dev"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["default"] == "dev"
    assert payload["profile_exists"] is False
    assert payload["path"].endswith("default_profile")


def test_set_default_rejects_invalid_name(runner):
    result = runner.invoke(cli, ["profile", "set-default", "../escape"])
    assert result.exit_code == 1
    assert "Invalid profile name" in result.output


def test_env_var_beats_saved_default(runner, monkeypatch):
    runner.invoke(cli, ["profile", "set-default", "dev"])
    monkeypatch.setenv("UPSCALER_PROFILE", "staging")
    result = runner.invoke(cli, ["profile", "current"])
    assert result.output.strip() == "staging"


def test_flag_beats_saved_default(runner):
    runner.invoke(cli, ["profile", "set-default", "dev"])
    result = runner.invoke(cli, ["--profile", "team_a", "profile", "current"])
    assert result.output.strip() == "team_a"
