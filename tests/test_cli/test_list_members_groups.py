"""Tests for `upscaler list members` and `list groups` (A093 T012)."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli
from upscaler_cli.errors import APIError


@pytest.fixture
def runner():
    return CliRunner()


def _ok(items):
    return {"success": True, "data": {"items": items, "total": len(items)}, "error": None}


def _members():
    return [{"id": "m1", "name": "Kong", "email": "k@x.io", "role": "OWNER", "blocked": False}]


class TestListMembers:
    def test_human_table_shows_focused_columns(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok(_members()))

            result = runner.invoke(cli, ["list", "members", "--search", "kong"])

        assert result.exit_code == 0, result.output
        assert "m1" in result.output
        assert "Kong" in result.output
        # Focused columns: role present, blocked not shown in the human table.
        assert "OWNER" in result.output
        call = MockClient.return_value.request.call_args
        assert call.args[1] == "/api/v1/members"
        assert call.kwargs["params"]["search"] == "kong"

    def test_show_disabled_flag_forwarded(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok(_members()))

            runner.invoke(cli, ["list", "members", "--show-disabled"])
            params = MockClient.return_value.request.call_args.kwargs["params"]
            assert params["show_disabled"] == "true"

    def test_json_mode_returns_full_envelope(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok(_members()))

            result = runner.invoke(cli, ["--json", "list", "members"])
            body = json.loads(result.output)
            # Full shape retained in JSON (blocked field present).
            assert body["data"]["items"][0]["blocked"] is False

    def test_permission_error_renders(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=APIError("You don't have permission", 403)
            )
            result = runner.invoke(cli, ["list", "members"])
        assert result.exit_code != 0
        assert "permission" in result.output.lower()


class TestListGroups:
    def test_lists_groups(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                return_value=_ok([{"id": "g1", "name": "Admins"}])
            )
            result = runner.invoke(cli, ["list", "groups"])
        assert result.exit_code == 0, result.output
        assert "Admins" in result.output
        assert MockClient.return_value.request.call_args.args[1] == "/api/v1/groups"
