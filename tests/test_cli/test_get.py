"""Tests for get CLI command."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_asset():
    return {
        "success": True,
        "data": {
            "id": "d_abc123",
            "title": "Safety Procedure",
            "type": "document",
            "status": "published",
        },
    }


class TestGetAsset:
    def test_get_default_table_output(self, runner, sample_asset):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=sample_asset)
            result = runner.invoke(cli, ["get", "d_abc123"])
            assert result.exit_code == 0
            # Table output should contain field/value pairs
            assert "title" in result.output
            assert "Safety Procedure" in result.output

    def test_get_failure_envelope_surfaces_error(self, runner):
        """A 200 {"success": false} envelope must fail loudly, not print an
        empty {} body."""
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
            result = runner.invoke(cli, ["get", "d_abc123"])
            assert result.exit_code != 0
            assert "Organization context required" in result.output

    def test_get_markdown_format(self, runner):
        mock_result = {
            "success": True,
            "data": {"markdown": "# Safety Procedure\n\nContent here."},
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["get", "d_abc123", "--format", "markdown"])
            assert result.exit_code == 0
            assert "# Safety Procedure" in result.output

    def test_get_course_definition_routes_to_assets(self, runner):
        # cd_ is an asset prefix: `get cd_…` must hit /api/v1/assets and surface
        # the course plus its lesson ids (read-back for the lesson-* operations).
        mock_result = {
            "success": True,
            "data": {
                "json": {
                    "asset_id": "cd_abc123",
                    "type": "course_definition",
                    "title": "Security Awareness",
                    "lessonDefinitions": [{"id": "cl_a", "title": "Phishing"}],
                }
            },
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "get", "cd_abc123"])
            assert result.exit_code == 0
            assert mock_request.call_args.args[1] == "/api/v1/assets/cd_abc123"
            data = json.loads(result.output)
            assert data["data"]["json"]["lessonDefinitions"][0]["id"] == "cl_a"

    def test_get_lesson_id_points_to_course(self, runner):
        # cl_ is not a standalone asset; the error must redirect to `get cd_…`
        # rather than the generic "unknown resource" message.
        result = runner.invoke(cli, ["get", "cl_abc123"])
        assert result.exit_code != 0
        assert "read through its course" in result.output
        assert "cd_" in result.output

    def test_get_json_mode(self, runner, sample_asset):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=sample_asset)
            result = runner.invoke(cli, ["--json", "get", "d_abc123"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True
            assert data["data"]["id"] == "d_abc123"

    def test_get_schema_format_json(self, runner):
        mock_result = {
            "success": True,
            "data": {
                "fields": [
                    {"key": "name", "type": "text", "label": "Name"},
                    {"key": "status", "type": "select", "label": "Status"},
                ]
            },
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "get", "d_abc123", "--format", "schema"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "fields" in data["data"]

    def test_get_draft_passes_param(self, runner):
        # --draft requests the unpublished working copy, forwarded to the API as
        # a draft query param so editors can verify changes before release.
        mock_result = {"success": True, "data": {"schema": []}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["get", "rd_1", "--format", "schema", "--draft"]
            )
            assert result.exit_code == 0
            params = mock_request.call_args.kwargs["params"]
            assert params.get("draft") in (True, "true")

    def test_get_without_draft_omits_param(self, runner):
        mock_result = {"success": True, "data": {"schema": []}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["get", "rd_1", "--format", "schema"])
            assert result.exit_code == 0
            params = mock_request.call_args.kwargs["params"]
            assert "draft" not in params

    def test_get_error(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(side_effect=RuntimeError("Not found"))
            result = runner.invoke(cli, ["get", "bad_id"])
            assert result.exit_code != 0

    def test_get_todo_surfaces_bookmark(self, runner):
        # `get to_…` routes to /api/v1/todos/{id}; a bookmark stored at
        # extra.bookmarkUrl must reach the caller in both output modes and must
        # not be stripped by CLI rendering.
        mock_result = {
            "success": True,
            "data": {
                "id": "to_abc123",
                "title": "Review",
                "extra": {"bookmarkUrl": "/document/d_1"},
            },
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            json_result = runner.invoke(cli, ["--json", "get", "to_abc123"])
            assert json_result.exit_code == 0
            assert mock_request.call_args.args[1] == "/api/v1/todos/to_abc123"
            data = json.loads(json_result.output)
            assert data["data"]["extra"]["bookmarkUrl"] == "/document/d_1"
            human_result = runner.invoke(cli, ["get", "to_abc123"])
            assert human_result.exit_code == 0
            assert "/document/d_1" in human_result.output
