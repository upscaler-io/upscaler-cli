"""Tests for the root CLI group's global flags (upscaler_cli.cli.main)."""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import _hoist_global_options, cli


@pytest.fixture
def runner():
    return CliRunner()


def _run_status(runner, args):
    """Invoke `status` with no stored token.

    `status` reports "not authenticated" and exits 0 without any network call
    when TokenStore.load() raises, so it is a hermetic probe for the resolved
    output mode. The command imports TokenStore at call time, so patch the
    source module path.
    """
    with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
        MockStore.return_value.load.side_effect = RuntimeError("no token")
        return runner.invoke(cli, args)


class TestGlobalJsonFlag:
    """The global --json flag stays accepted and idempotent even when
    $UPSCALER_OUTPUT=json already makes JSON the runtime default."""

    def test_json_flag_accepted_when_env_already_json(self, runner, monkeypatch):
        # An explicit --json on top of the env default is idempotent: it yields
        # JSON, not a usage/parse error (exit 2).
        monkeypatch.setenv("UPSCALER_OUTPUT", "json")
        result = _run_status(runner, ["--json", "status"])
        assert result.exit_code == 0
        assert json.loads(result.output)["authenticated"] is False

    def test_env_json_is_the_default_without_flag(self, runner, monkeypatch):
        # With the env var set and no flag, JSON is already the default.
        monkeypatch.setenv("UPSCALER_OUTPUT", "json")
        result = _run_status(runner, ["status"])
        assert result.exit_code == 0
        assert json.loads(result.output)["authenticated"] is False

    def test_no_json_overrides_env_default(self, runner, monkeypatch):
        # --no-json forces human output even when the env var makes JSON default.
        monkeypatch.setenv("UPSCALER_OUTPUT", "json")
        result = _run_status(runner, ["--no-json", "status"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.output

    def test_json_flag_accepted_without_env(self, runner):
        # No env var (conftest strips it): explicit --json still yields JSON.
        result = _run_status(runner, ["--json", "status"])
        assert result.exit_code == 0
        assert json.loads(result.output)["authenticated"] is False


class TestHoistGlobalOptions:
    """Unit tests for the arg reordering that powers position independence."""

    def test_boolean_flag_after_subcommand_moves_to_front(self):
        assert _hoist_global_options(["health", "--json"]) == ["--json", "health"]

    def test_flag_already_in_front_is_unchanged(self):
        assert _hoist_global_options(["--json", "health"]) == ["--json", "health"]

    def test_nested_subcommand_flag_is_hoisted_over_whole_chain(self):
        # A single top-level hoist covers nested groups: the flag lands ahead
        # of the whole subcommand chain.
        assert _hoist_global_options(["list", "entries", "--json", "--definition-id", "rg_x"]) == [
            "--json",
            "list",
            "entries",
            "--definition-id",
            "rg_x",
        ]

    def test_value_option_carries_its_value(self):
        assert _hoist_global_options(["status", "--profile", "dev"]) == [
            "--profile",
            "dev",
            "status",
        ]

    def test_value_option_equals_form_is_single_token(self):
        assert _hoist_global_options(["status", "--profile=dev"]) == [
            "--profile=dev",
            "status",
        ]

    def test_short_flags_are_hoisted(self):
        assert _hoist_global_options(["create", "-q", "-v"]) == ["-q", "-v", "create"]

    def test_multiple_globals_preserve_subcommand_order(self):
        assert _hoist_global_options(
            ["entry", "create", "--json", "--server", "https://x", "--id", "rd_1"]
        ) == ["--json", "--server", "https://x", "entry", "create", "--id", "rd_1"]

    def test_double_dash_stops_hoisting(self):
        # Tokens after the end-of-options marker are left in place.
        assert _hoist_global_options(["search", "--", "--json"]) == [
            "search",
            "--",
            "--json",
        ]

    def test_non_global_tokens_keep_their_order(self):
        assert _hoist_global_options(["a", "b", "c"]) == ["a", "b", "c"]

    def test_value_taking_option_shields_a_flag_spelled_value(self):
        # `--title --quiet` means the title is the literal "--quiet"; it must
        # not be hoisted as the global --quiet flag.
        assert _hoist_global_options(["entry", "update", "--title", "--quiet"], {"--title"}) == [
            "entry",
            "update",
            "--title",
            "--quiet",
        ]

    def test_boolean_subcommand_flag_does_not_shield_following_global(self):
        # --dry-run takes no value, so a following --json is still hoisted.
        assert _hoist_global_options(["asset", "create", "--dry-run", "--json"], {"--title"}) == [
            "--json",
            "asset",
            "create",
            "--dry-run",
        ]

    def test_real_cli_value_option_shields_flag_value(self):
        # End-to-end against the actual collected option set: a value spelled
        # like a global flag stays put, while a genuine trailing global hoists.
        from upscaler_cli.cli.main import _value_taking_subcommand_opts, cli

        value_opts = _value_taking_subcommand_opts(cli)
        assert "--title" in value_opts and "--dry-run" not in value_opts
        assert _hoist_global_options(["entry", "create", "--title", "--quiet"], value_opts) == [
            "entry",
            "create",
            "--title",
            "--quiet",
        ]
        assert (
            _hoist_global_options(["asset", "create", "--dry-run", "--json"], value_opts)[0]
            == "--json"
        )


class TestGlobalFlagPositionIndependent:
    """End-to-end: global flags work after the subcommand, not just before."""

    def test_json_after_subcommand_is_accepted(self, runner):
        # Regression for `upscaler health --json` -> "No such option: --json".
        result = _run_status(runner, ["status", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["authenticated"] is False

    def test_json_before_subcommand_still_works(self, runner):
        result = _run_status(runner, ["--json", "status"])
        assert result.exit_code == 0
        assert json.loads(result.output)["authenticated"] is False

    def test_no_json_after_subcommand_overrides_env_default(self, runner, monkeypatch):
        monkeypatch.setenv("UPSCALER_OUTPUT", "json")
        result = _run_status(runner, ["status", "--no-json"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.output

    def test_unknown_option_after_subcommand_still_errors(self, runner):
        # Hoisting must not swallow non-global options: an unknown option after
        # the subcommand still reaches the subcommand parser and is rejected.
        result = runner.invoke(cli, ["status", "--not-a-global-flag"])
        assert result.exit_code == 2
        assert "no such option" in result.output.lower()

    def test_server_value_after_subcommand_is_consumed(self, runner):
        # A value option after the subcommand grabs its value (not the
        # subcommand name) and threads through without a parse error: the
        # command runs (exit 0) rather than failing with "Missing command".
        result = _run_status(runner, ["status", "--server", "https://example.com"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.output
