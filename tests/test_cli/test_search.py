"""Tests for search CLI command."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _patch_search(**overrides):
    """Return context manager patching CLIConfig, TokenStore, UpscalerClient for search."""
    return (
        patch("upscaler_cli.config.CLIConfig", **overrides.get("config", {})),
        patch("upscaler_cli.auth.token_store.TokenStore"),
        patch("upscaler_cli.client.UpscalerClient", **overrides.get("client", {})),
    )


class TestSearch:
    def test_search_table_output(self, runner):
        mock_result = {
            "success": True,
            "data": [
                {
                    "score": 0.95, "asset_id": "d_1",
                    "asset_title": "Safety Manual",
                    "asset_type": "document",
                },
            ],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["search", "safety"])
            assert result.exit_code == 0
            assert "Safety Manual" in result.output

    def test_search_json_output(self, runner):
        mock_result = {"success": True, "data": []}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "search", "safety"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True

    def test_search_no_results(self, runner):
        mock_result = {"success": True, "data": []}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["search", "nonexistent"])
            assert "No results found" in result.output

    def test_search_failure_envelope_surfaces_error(self, runner):
        """A 200 {"success": false} envelope must fail loudly, not print
        "No results found"."""
        mock_result = {
            "success": False,
            "error": {"message": "Organization context required"},
            "data": [],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["search", "anything"])
            assert result.exit_code != 0
            assert "Organization context required" in result.output
            assert "No results found" not in result.output

    def test_search_with_options(self, runner):
        mock_result = {
            "success": True,
            "data": [
                {"score": 0.8, "asset_id": "p_1", "asset_title": "Policy", "asset_type": "policy"},
            ],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(
                cli,
                ["search", "compliance", "--limit", "5", "--type", "policy"],
            )
            assert result.exit_code == 0
            assert "Policy" in result.output
            # Verify the request was called with correct params
            call_args = MockClient.return_value.request.call_args
            body = call_args[1]["json"] if "json" in call_args[1] else call_args[0][2]
            assert body["limit"] == 5
            assert body["asset_type"] == "policy"

    def test_search_error(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=RuntimeError("Connection refused"),
            )
            result = runner.invoke(cli, ["search", "test"])
            assert result.exit_code != 0
