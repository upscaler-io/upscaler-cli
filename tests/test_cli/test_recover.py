"""Tests for the `upscaler recover` command (A093 T021)."""

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli
from upscaler_cli.errors import APIError


@pytest.fixture
def runner():
    return CliRunner()


def _ok(asset_id):
    return {"success": True, "data": {"id": asset_id}, "error": None}


class TestRecoverHappyPath:
    @pytest.mark.parametrize(
        "asset_id,mutation",
        [
            ("i_1", "recoverItem"),
            ("r_1", "recoverRecord"),
            ("d_1", "recoverDocumentDefinition"),
            ("rd_1", "recoverRecordDefinition"),
        ],
    )
    def test_recovers_and_suggests_get(self, runner, asset_id, mutation):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok(asset_id))

            result = runner.invoke(cli, ["recover", asset_id])

        assert result.exit_code == 0, result.output
        assert f"upscaler get {asset_id}" in result.output
        call = MockClient.return_value.request.call_args
        assert call.args[0] == "POST"
        assert call.args[1] == f"/api/v1/assets/{asset_id}/recover"


class TestDryRun:
    def test_dry_run_makes_no_http_call(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()

            result = runner.invoke(cli, ["recover", "r_1", "--dry-run"])

        assert result.exit_code == 0
        assert "recoverRecord" in result.output
        assert "dry-run" in result.output
        MockClient.return_value.request.assert_not_called()

    def test_dry_run_unknown_prefix_reports_fallback(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(cli, ["recover", "td_1", "--dry-run"])
        assert result.exit_code == 0
        assert "recoverDeletedAsset" in result.output
        MockClient.return_value.request.assert_not_called()


class TestErrors:
    def test_malformed_id_fails_before_http(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(cli, ["recover", "not-an-id"])
        assert result.exit_code != 0
        assert "recognizable" in result.output
        MockClient.return_value.request.assert_not_called()

    def test_permission_error_rendered(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=APIError("You don't have permission", 403)
            )
            result = runner.invoke(cli, ["recover", "td_1"])
        assert result.exit_code != 0
        assert "permission" in result.output.lower()
