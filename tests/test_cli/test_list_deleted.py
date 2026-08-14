"""Tests for `upscaler list deleted` (A093 T022)."""

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


def _deleted():
    return [
        {
            "id": "i_1",
            "title": "Old Item",
            "assetType": "item",
            "deletedAt": "2026-07-13",
            "deletedBy": {"id": "m1", "name": "Kong"},
        }
    ]


class TestListDeleted:
    def test_renders_deleted_assets(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok(_deleted()))

            result = runner.invoke(cli, ["list", "deleted"])

        assert result.exit_code == 0, result.output
        assert "Old Item" in result.output
        # deletedBy collapses to the member name in the human table.
        assert "Kong" in result.output
        assert MockClient.return_value.request.call_args.args[1] == "/api/v1/trash"

    def test_search_forwarded(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok(_deleted()))
            runner.invoke(cli, ["list", "deleted", "--search", "old"])
            params = MockClient.return_value.request.call_args.kwargs["params"]
            assert params["search"] == "old"

    def test_permission_error_names_owner_admin(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=APIError("Requires OWNER or ADMIN role", 403)
            )
            result = runner.invoke(cli, ["list", "deleted"])
        assert result.exit_code != 0
        assert "OWNER" in result.output or "ADMIN" in result.output
