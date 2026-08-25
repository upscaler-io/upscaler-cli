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

    def test_get_accepts_multiple_formats(self, runner):
        # The REST API and MCP tool both take a list of formats. The CLI used to
        # be limited to one, so json+schema in a single read was unreachable here.
        mock_result = {
            "success": True,
            "data": {"json": {"asset_id": "rg_1"}, "schema": {"fields": []}},
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["get", "rg_1", "--format", "json,schema"])
            assert result.exit_code == 0
            assert mock_request.call_args.kwargs["params"]["format"] == "json,schema"

    def test_get_format_is_repeatable(self, runner):
        mock_result = {"success": True, "data": {"json": {}, "markdown": "# T"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["get", "rg_1", "--format", "json", "--format", "markdown"]
            )
            assert result.exit_code == 0
            assert mock_request.call_args.kwargs["params"]["format"] == "json,markdown"
            # Labelled sections, because two bodies in a row are otherwise
            # indistinguishable. A single format stays unlabelled and pipeable.
            assert "--- markdown ---" in result.output

    def test_get_rejects_an_unknown_format(self, runner):
        result = runner.invoke(cli, ["get", "rg_1", "--format", "yaml"])
        assert result.exit_code != 0
        assert "yaml" in result.output

    def test_get_lane_passes_param(self, runner):
        mock_result = {"success": True, "data": {"json": {"lane": "designer"}}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "get", "rg_1", "--lane", "designer"])
            assert result.exit_code == 0
            assert mock_request.call_args.kwargs["params"]["lane"] == "designer"

    def test_get_without_lane_omits_param(self, runner):
        # The server owns the default; the client must not hard-code one.
        mock_result = {"success": True, "data": {"json": {}}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "get", "rg_1"])
            assert result.exit_code == 0
            assert "lane" not in mock_request.call_args.kwargs["params"]

    def test_get_rejects_lane_and_draft_together(self, runner):
        # The server gives draft precedence, so `--lane published --draft` would
        # silently answer designer. Fail rather than contradict the request.
        result = runner.invoke(
            cli, ["get", "rg_1", "--lane", "published", "--draft"]
        )
        assert result.exit_code != 0
        assert "pass one, not both" in result.output

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
        # Todos are assets: `get to_…` goes to /api/v1/assets like every other
        # prefix, so the payload arrives under data.json rather than bare. A
        # bookmark stored at extra.bookmarkUrl must survive that move and reach
        # the caller in both output modes.
        mock_result = {
            "success": True,
            "data": {
                "json": {
                    "title": "Review",
                    "extra": {"bookmarkUrl": "/document/d_1"},
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
            json_result = runner.invoke(cli, ["--json", "get", "to_abc123"])
            assert json_result.exit_code == 0
            assert mock_request.call_args.args[1] == "/api/v1/assets/to_abc123"
            data = json.loads(json_result.output)
            assert data["data"]["json"]["extra"]["bookmarkUrl"] == "/document/d_1"
            human_result = runner.invoke(cli, ["get", "to_abc123"])
            assert human_result.exit_code == 0
            assert "/document/d_1" in human_result.output

    def test_get_todo_honours_format(self, runner):
        # The old /api/v1/todos route ignored --format entirely, so `get to_…
        # --format markdown` silently returned a bare todo object instead.
        mock_result = {"success": True, "data": {"markdown": "# Review"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["get", "to_abc123", "--format", "markdown"])
            assert result.exit_code == 0
            assert mock_request.call_args.kwargs["params"]["format"] == "markdown"
            assert "# Review" in result.output

    def test_get_todo_by_explicit_type_still_uses_the_todo_route(self, runner):
        # --type todo is deprecated but must keep working for one release: the
        # bare-object endpoint is a public surface some scripts still read.
        mock_result = {"success": True, "data": {"id": "to_abc123"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "get", "to_abc123", "--type", "todo"])
            assert result.exit_code == 0
            assert mock_request.call_args.args[1] == "/api/v1/todos/to_abc123"
