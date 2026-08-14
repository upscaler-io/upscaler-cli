"""Tests for asset CLI commands."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestAssetCreate:
    def test_create_asset(self, runner):
        mock_result = {"success": True, "data": {"assetId": "rg_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "create",
                    "--type",
                    "register_definition",
                    "--data",
                    '{"title": "My Register"}',
                ],
            )
            assert result.exit_code == 0
            assert "rg_001" in result.output
            # Verify payload structure
            call_kwargs = mock_request.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload["operation"] == "create"
            assert payload["asset_type"] == "register_definition"
            assert payload["data"] == {"title": "My Register"}

    def test_create_asset_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "create",
                "--type",
                "register_definition",
                "--data",
                '{"title": "My Register"}',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()

    def test_create_asset_dry_run_json_mode(self, runner):
        result = runner.invoke(
            cli,
            [
                "--json",
                "asset",
                "create",
                "--type",
                "register_definition",
                "--data",
                '{"title": "My Register"}',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["operation"] == "create"
        assert data["payload"]["asset_type"] == "register_definition"

    def test_create_asset_json_mode(self, runner):
        mock_result = {"success": True, "data": {"assetId": "rg_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "asset",
                    "create",
                    "--type",
                    "register_definition",
                    "--data",
                    '{"title": "My Register"}',
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True

    def test_create_asset_quiet_prints_only_id(self, runner):
        # --quiet suppresses the "Asset create:" label and the full envelope,
        # emitting just the created id (one line) for cheap agent consumption.
        mock_result = {
            "success": True,
            "data": {"assetId": "rg_001", "title": "My Register", "values": "x" * 5000},
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
                [
                    "--quiet",
                    "asset",
                    "create",
                    "--type",
                    "register_definition",
                    "--data",
                    '{"title": "My Register"}',
                ],
            )
            assert result.exit_code == 0
            assert result.output.strip() == "rg_001"

    def test_create_asset_dry_run_quiet_omits_body(self, runner):
        # --quiet --dry-run prints a one-line summary, never the (potentially
        # huge) payload body.
        big = "# Heading\n" * 1000
        result = runner.invoke(
            cli,
            [
                "--quiet",
                "asset",
                "create",
                "--type",
                "register_definition",
                "--data",
                json.dumps({"title": "My Register", "values": big}),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()
        assert "# Heading" not in result.output
        assert len(result.output.splitlines()) == 1

    def test_create_asset_invalid_json(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "create",
                "--type",
                "register_definition",
                "--data",
                "not json",
            ],
        )
        assert result.exit_code != 0

    def test_create_asset_missing_type(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "create",
                "--data",
                '{"title": "No Type"}',
            ],
        )
        assert result.exit_code != 0

    def test_create_asset_invalid_type_rejected(self, runner):
        # --type is constrained to the real definition types; a bogus value is
        # rejected by the CLI before any request is sent.
        result = runner.invoke(
            cli,
            ["asset", "create", "--type", "bogus_type", "--data", '{"title": "X"}'],
        )
        assert result.exit_code != 0
        assert "bogus_type" in result.output

    def test_create_asset_invalid_type_rejected_on_dry_run(self, runner):
        # Validation happens at parse time, so --dry-run no longer echoes a bogus
        # type as if it were valid.
        result = runner.invoke(
            cli,
            [
                "asset",
                "create",
                "--type",
                "bogus_type",
                "--data",
                '{"title": "X"}',
                "--dry-run",
            ],
        )
        assert result.exit_code != 0

    def test_create_asset_surfaces_envelope_error(self, runner):
        # The /assets route returns failures as HTTP 200 with success=false; the
        # CLI must print the error and exit non-zero rather than an empty id.
        mock_result = {
            "success": False,
            "error": {"error_code": "VALUE_VALIDATION_ERROR", "message": "values rejected"},
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
                ["asset", "create", "--type", "document_definition", "--data", '{"title": "X"}'],
            )
            assert result.exit_code != 0
            assert "values rejected" in result.output


class TestAssetUpdate:
    def test_update_asset(self, runner):
        mock_result = {"success": True, "data": {"assetId": "rg_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "update",
                    "--asset-id",
                    "rg_001",
                    "--data",
                    '{"title": "New Title"}',
                ],
            )
            assert result.exit_code == 0
            assert "rg_001" in result.output

    def test_update_asset_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "update",
                "--asset-id",
                "rg_001",
                "--data",
                '{"title": "New Title"}',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()


class TestAssetUpdateContent:
    def test_update_content(self, runner):
        mock_result = {"success": True, "data": {"assetId": "rg_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "update-content",
                    "--asset-id",
                    "rg_001",
                    "--data",
                    '{"values": [{"type": "paragraph"}]}',
                ],
            )
            assert result.exit_code == 0

    def test_update_content_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "update-content",
                "--asset-id",
                "rg_001",
                "--data",
                '{"values": []}',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()


class TestAssetDelete:
    def test_delete_asset_confirmed(self, runner):
        mock_result = {"success": True, "data": {"assetId": "rg_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
            patch("upscaler_cli.cli.helpers.confirm_destructive", return_value=True),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["asset", "delete", "--asset-id", "rg_001"])
            assert result.exit_code == 0

    def test_delete_asset_cancelled(self, runner):
        with patch("upscaler_cli.cli.helpers.confirm_destructive", return_value=False):
            result = runner.invoke(cli, ["asset", "delete", "--asset-id", "rg_001"])
            assert "Cancelled" in result.output or result.exit_code == 0

    def test_delete_asset_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "delete",
                "--asset-id",
                "rg_001",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()

    def test_delete_asset_dry_run_json_mode(self, runner):
        result = runner.invoke(
            cli,
            [
                "--json",
                "asset",
                "delete",
                "--asset-id",
                "rg_001",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["operation"] == "delete"


class TestAssetSetPermissions:
    def test_set_permissions(self, runner):
        mock_result = {"success": True, "data": {"assetId": "rg_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-permissions",
                    "--asset-id",
                    "rg_001",
                    "--data",
                    '{"roles": ["admin"]}',
                ],
            )
            assert result.exit_code == 0


class TestAssetAddToRelease:
    def test_add_to_release(self, runner):
        mock_result = {"success": True, "data": {"assetId": "rg_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "add-to-release",
                    "--asset-id",
                    "rg_001",
                    "--data",
                    '{"releaseId": "rel_1"}',
                ],
            )
            assert result.exit_code == 0


class TestAssetAddTask:
    def test_add_task(self, runner):
        mock_result = {
            "success": True,
            "data": {"assetId": "rd_001", "taskDefinitionId": "td_999", "title": "T1"},
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "add-task",
                    "--asset-id",
                    "rd_001",
                    "--title",
                    "Meeting Details",
                    "--description",
                    "Capture metadata",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "add_task_definition"
            assert payload["asset_id"] == "rd_001"
            assert payload["data"] == {
                "title": "Meeting Details",
                "description": "Capture metadata",
            }

    def test_add_task_minimal(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "add-task",
                    "--asset-id",
                    "rd_001",
                    "--title",
                    "Task",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["data"] == {"title": "Task"}

    def test_add_task_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "--json",
                "asset",
                "add-task",
                "--asset-id",
                "rd_001",
                "--title",
                "Task",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["operation"] == "add_task_definition"


class TestAssetSetTaskValues:
    def test_set_task_values_with_data(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-task-values",
                    "--asset-id",
                    "rd_001",
                    "--task-id",
                    "td_xyz",
                    "--data",
                    '{"values": "## Section\\n---\\n<form-text></form-text>"}',
                    "--values-type",
                    "markdown",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "set_task_definition_values"
            assert payload["data"]["taskDefinitionId"] == "td_xyz"
            assert payload["data"]["valuesType"] == "markdown"
            assert "## Section" in payload["data"]["values"]

    def test_set_task_values_with_values_file(self, runner, tmp_path):
        body = tmp_path / "task1.md"
        body.write_text("## Heading\n\n---\n\n<form-text></form-text>")

        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-task-values",
                    "--asset-id",
                    "rd_001",
                    "--task-id",
                    "td_xyz",
                    "--values-file",
                    str(body),
                    "--values-type",
                    "markdown",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["data"]["values"] == body.read_text()
            assert payload["data"]["valuesType"] == "markdown"

    def test_set_task_values_with_slatejson_file_parses_array(self, runner, tmp_path):
        # A slateJson body file holds a JSON array of Slate nodes. The CLI must
        # send it as a parsed list, not a raw string (a string is silently
        # dropped by the platform).
        nodes = [{"type": "paragraph", "children": [{"text": "hi"}]}]
        body = tmp_path / "task1.json"
        body.write_text(json.dumps(nodes))

        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-task-values",
                    "--asset-id",
                    "rd_001",
                    "--task-id",
                    "td_xyz",
                    "--values-file",
                    str(body),
                    "--values-type",
                    "slateJson",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["data"]["values"] == nodes
            assert payload["data"]["valuesType"] == "slateJson"

    def test_set_task_values_with_invalid_slatejson_file_errors(self, runner, tmp_path):
        # A slateJson file that is not valid JSON must fail loudly at parse time,
        # not be sent as a raw string. The client is mocked to succeed, so the
        # only thing that can produce a non-zero exit is the parse rejection.
        body = tmp_path / "task1.json"
        body.write_text("## not json")
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                return_value={"success": True, "data": {}}
            )
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-task-values",
                    "--asset-id",
                    "rd_001",
                    "--task-id",
                    "td_xyz",
                    "--values-file",
                    str(body),
                    "--values-type",
                    "slateJson",
                ],
            )
        assert result.exit_code != 0

    def test_set_task_values_requires_content(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "set-task-values",
                "--asset-id",
                "rd_001",
                "--task-id",
                "td_xyz",
            ],
        )
        assert result.exit_code != 0

    def test_set_task_values_rejects_both_inputs(self, runner, tmp_path):
        body = tmp_path / "task1.md"
        body.write_text("## Heading")
        result = runner.invoke(
            cli,
            [
                "asset",
                "set-task-values",
                "--asset-id",
                "rd_001",
                "--task-id",
                "td_xyz",
                "--data",
                '{"values": "x"}',
                "--values-file",
                str(body),
            ],
        )
        assert result.exit_code != 0

    def test_set_task_values_data_without_values_key(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "set-task-values",
                "--asset-id",
                "rd_001",
                "--task-id",
                "td_xyz",
                "--data",
                '{"taskDefinitionId": "td_other"}',
            ],
        )
        assert result.exit_code != 0


class TestAssetSetTaskCondition:
    def test_set_task_condition(self, runner):
        condition = {
            "ast": {
                "operator": "&&",
                "clauseGroups": {
                    "_default": {
                        "id": "_default",
                        "operator": "&&",
                        "conditionClauses": {
                            "_default": {
                                "id": "_default",
                                "left": {
                                    "subjectType": "FIELD",
                                    "valueType": "task",
                                    "value": {"key": "td_prev", "path": []},
                                },
                                "type": "task",
                                "operator": "isCompleted",
                            }
                        },
                    }
                },
            }
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-task-condition",
                    "--asset-id",
                    "rd_001",
                    "--task-id",
                    "td_next",
                    "--data",
                    json.dumps({"condition": condition}),
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "set_task_definition_condition"
            assert payload["data"]["taskDefinitionId"] == "td_next"
            assert payload["data"]["condition"] == condition

    def test_set_task_condition_missing_condition_key(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "set-task-condition",
                "--asset-id",
                "rd_001",
                "--task-id",
                "td_next",
                "--data",
                '{"something": "else"}',
            ],
        )
        assert result.exit_code != 0


class TestAssetApiError:
    def test_api_error_human_mode(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(side_effect=RuntimeError("Server error"))
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "create",
                    "--type",
                    "register_definition",
                    "--data",
                    '{"title": "Fail"}',
                ],
            )
            assert result.exit_code != 0

    def test_api_error_json_mode(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(side_effect=RuntimeError("Server error"))
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "asset",
                    "create",
                    "--type",
                    "register_definition",
                    "--data",
                    '{"title": "Fail"}',
                ],
            )
            assert result.exit_code != 0


class TestAssetAddLesson:
    def test_add_lesson(self, runner):
        mock_result = {
            "success": True,
            "data": {"assetId": "cd_001", "lessonDefinitionId": "cl_999", "title": "L1"},
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "add-lesson",
                    "--asset-id",
                    "cd_001",
                    "--title",
                    "Phishing Basics",
                    "--description",
                    "Intro module",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "add_lesson_definition"
            assert payload["asset_id"] == "cd_001"
            assert payload["data"] == {
                "title": "Phishing Basics",
                "description": "Intro module",
            }

    def test_add_lesson_minimal(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                ["asset", "add-lesson", "--asset-id", "cd_001", "--title", "Lesson"],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["data"] == {"title": "Lesson"}

    def test_add_lesson_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "--json",
                "asset",
                "add-lesson",
                "--asset-id",
                "cd_001",
                "--title",
                "Lesson",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["operation"] == "add_lesson_definition"


class TestAssetSetLessonMetadata:
    def test_set_lesson_title(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-lesson-title",
                    "--asset-id",
                    "cd_001",
                    "--lesson-id",
                    "cl_xyz",
                    "--title",
                    "Renamed",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "set_lesson_definition_title"
            assert payload["data"] == {"lessonDefinitionId": "cl_xyz", "title": "Renamed"}

    def test_set_lesson_description(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-lesson-description",
                    "--asset-id",
                    "cd_001",
                    "--lesson-id",
                    "cl_xyz",
                    "--description",
                    "New desc",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "set_lesson_definition_description"
            assert payload["data"] == {"lessonDefinitionId": "cl_xyz", "description": "New desc"}


class TestAssetSetLessonValues:
    def test_set_lesson_values_with_data(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-lesson-values",
                    "--asset-id",
                    "cd_001",
                    "--lesson-id",
                    "cl_xyz",
                    "--data",
                    '{"values": "## Lesson body"}',
                    "--values-type",
                    "markdown",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "set_lesson_definition_values"
            assert payload["data"]["lessonDefinitionId"] == "cl_xyz"
            assert payload["data"]["valuesType"] == "markdown"
            assert "## Lesson body" in payload["data"]["values"]

    def test_set_lesson_values_with_slatejson_file_parses_array(self, runner, tmp_path):
        nodes = [{"type": "paragraph", "children": [{"text": "hi"}]}]
        body = tmp_path / "lesson1.json"
        body.write_text(json.dumps(nodes))

        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "set-lesson-values",
                    "--asset-id",
                    "cd_001",
                    "--lesson-id",
                    "cl_xyz",
                    "--values-file",
                    str(body),
                    "--values-type",
                    "slateJson",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["data"]["values"] == nodes
            assert payload["data"]["valuesType"] == "slateJson"

    def test_set_lesson_values_requires_content(self, runner):
        result = runner.invoke(
            cli,
            [
                "asset",
                "set-lesson-values",
                "--asset-id",
                "cd_001",
                "--lesson-id",
                "cl_xyz",
            ],
        )
        assert result.exit_code != 0


class TestAssetRemoveAndMoveLesson:
    def test_remove_lesson(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "remove-lesson",
                    "--asset-id",
                    "cd_001",
                    "--lesson-id",
                    "cl_xyz",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "remove_lesson_definition"
            assert payload["data"] == {"lessonDefinitionId": "cl_xyz"}

    def test_move_lesson(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value={"success": True, "data": {}})
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "asset",
                    "move-lesson",
                    "--asset-id",
                    "cd_001",
                    "--from-id",
                    "cl_a",
                    "--to-id",
                    "cl_b",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "move_lesson_definition"
            assert payload["data"] == {"fromId": "cl_a", "toId": "cl_b"}

    def test_move_lesson_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "--json",
                "asset",
                "move-lesson",
                "--asset-id",
                "cd_001",
                "--from-id",
                "cl_a",
                "--to-id",
                "cl_b",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["operation"] == "move_lesson_definition"
