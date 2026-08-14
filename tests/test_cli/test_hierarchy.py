"""Tests for hierarchy CLI command."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_hierarchy():
    return {
        "success": True,
        "data": {
            "id": "root_1",
            "title": "Operations Manual",
            "type": "folder",
            "children": [
                {
                    "id": "ch_1",
                    "title": "Safety Section",
                    "type": "document",
                    "children": [],
                },
                {
                    "id": "ch_2",
                    "title": "Compliance Section",
                    "type": "document",
                    "children": [],
                },
            ],
        },
    }


class TestHierarchy:
    def test_hierarchy_tree_output(self, runner, sample_hierarchy):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=sample_hierarchy)
            result = runner.invoke(cli, ["hierarchy", "root_1"])
            assert result.exit_code == 0
            assert "Operations Manual" in result.output
            assert "Safety Section" in result.output
            assert "Compliance Section" in result.output

    def test_hierarchy_failure_envelope_surfaces_error(self, runner):
        """A 200 {"success": false} envelope must fail loudly, not render an
        empty tree."""
        mock_result = {
            "success": False,
            "error": {"message": "Organization context required"},
            "data": {},
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["hierarchy", "root_1"])
            assert result.exit_code != 0
            assert "Organization context required" in result.output

    def test_hierarchy_tree_uses_connectors(self, runner, sample_hierarchy):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=sample_hierarchy)
            result = runner.invoke(cli, ["hierarchy", "root_1"])
            # Tree connectors from format_tree
            assert "\u251c\u2500\u2500" in result.output or "\u2514\u2500\u2500" in result.output

    def test_hierarchy_json_mode(self, runner, sample_hierarchy):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=sample_hierarchy)
            result = runner.invoke(cli, ["--json", "hierarchy", "root_1"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True
            assert data["data"]["id"] == "root_1"
            assert len(data["data"]["children"]) == 2

    def test_hierarchy_with_depth_option(self, runner, sample_hierarchy):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=sample_hierarchy)
            result = runner.invoke(cli, ["hierarchy", "root_1", "--depth", "5"])
            assert result.exit_code == 0
            # Verify depth param was passed to the request
            call_args = MockClient.return_value.request.call_args
            params = call_args[1].get("params", call_args[0][2] if len(call_args[0]) > 2 else {})
            assert params["depth"] == 5

    def test_hierarchy_error(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(side_effect=RuntimeError("Not found"))
            result = runner.invoke(cli, ["hierarchy", "bad_id"])
            assert result.exit_code != 0
