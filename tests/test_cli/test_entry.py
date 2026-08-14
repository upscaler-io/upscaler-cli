"""Tests for entry CLI commands."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestEntryCreate:
    def test_create_entry(self, runner):
        mock_result = {"success": True, "data": {"id": "i_001"}}
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
                    "entry",
                    "create",
                    "--definition-id",
                    "rg_123",
                    "--data",
                    '{"title": "New item"}',
                ],
            )
            assert result.exit_code == 0
            assert "i_001" in result.output
            # Verify payload structure
            call_kwargs = mock_request.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload["operation"] == "create"
            assert payload["definition_id"] == "rg_123"
            assert payload["data"] == {"title": "New item"}
            # --note omitted: payload carries no note key.
            assert "note" not in payload

    def test_create_entry_note_passes_through(self, runner):
        mock_result = {"success": True, "data": {"id": "i_001"}}
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
                    "entry",
                    "create",
                    "--definition-id",
                    "rg_123",
                    "--data",
                    '{"title": "New item"}',
                    "--note",
                    "Prefilled from Q2 report",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "create"
            # --note is folded into the data object; never a top-level key.
            assert payload["data"]["note"] == "Prefilled from Q2 report"
            assert "note" not in payload

    def test_create_help_mentions_draft_review(self, runner):
        result = runner.invoke(cli, ["entry", "create", "--help"])
        assert result.exit_code == 0
        assert "draft" in result.output.lower()
        assert "review" in result.output.lower()

    def test_create_entry_quiet_prints_only_id(self, runner):
        # --quiet on a record create skips the per-task field enrichment (extra
        # GET /tasks calls) and prints just the new id.
        mock_result = {
            "success": True,
            "data": {"id": "r_001", "tasks": [{"id": "t_1"}, {"id": "t_2"}]},
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
                    "--quiet",
                    "entry",
                    "create",
                    "--definition-id",
                    "rd_123",
                    "--data",
                    '{"title": "New record"}',
                ],
            )
            assert result.exit_code == 0
            assert result.output.strip() == "r_001"
            # Only the create POST should fire — no per-task enrichment GETs.
            assert mock_request.call_count == 1

    def test_create_entry_with_file_data(self, runner, tmp_path):
        data_file = tmp_path / "payload.json"
        data_file.write_text('{"title": "From file"}')
        mock_result = {"success": True, "data": {"id": "i_002"}}
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
                    "entry",
                    "create",
                    "--definition-id",
                    "rg_123",
                    "--data",
                    f"@{data_file}",
                ],
            )
            assert result.exit_code == 0
            assert "i_002" in result.output

    def test_create_entry_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "entry",
                "create",
                "--definition-id",
                "rg_123",
                "--data",
                '{"title": "Preview"}',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()

    def test_create_entry_dry_run_json_mode(self, runner):
        result = runner.invoke(
            cli,
            [
                "--json",
                "entry",
                "create",
                "--definition-id",
                "rg_123",
                "--data",
                '{"title": "Preview"}',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["operation"] == "create"
        assert data["payload"]["definition_id"] == "rg_123"

    def test_create_entry_json_mode(self, runner):
        mock_result = {"success": True, "data": {"id": "i_003"}}
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
                    "entry",
                    "create",
                    "--definition-id",
                    "rg_123",
                    "--data",
                    '{"title": "JSON out"}',
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True

    def test_create_entry_invalid_json(self, runner):
        result = runner.invoke(
            cli,
            [
                "entry",
                "create",
                "--definition-id",
                "rg_123",
                "--data",
                "not json",
            ],
        )
        assert result.exit_code != 0

    def test_create_entry_missing_required(self, runner):
        result = runner.invoke(cli, ["entry", "create"])
        assert result.exit_code != 0

    def test_bare_ff_payload_rejected_with_clear_error(self, runner):
        # The REST `/entries` endpoint reads form-field values only from
        # `data.values`. A bare `{ff_*: ...}` payload looks accepted (success
        # response, entry id returned) but values are silently dropped on the
        # server. Fail fast at the CLI so the caller gets a hint pointing at
        # the canonical wrapper shape.
        result = runner.invoke(
            cli,
            [
                "entry",
                "create",
                "--definition-id",
                "rg_123",
                "--data",
                '{"ff_xxx": "value"}',
            ],
        )
        assert result.exit_code != 0
        assert "ff_xxx" in result.output
        assert "values" in result.output

    def test_mixed_title_and_bare_ff_payload_rejected(self, runner):
        # `title` is legitimately top-level (backend reads it), but the ff_*
        # key would still be dropped. Reject so the caller fixes the ff_*
        # keys before retrying.
        result = runner.invoke(
            cli,
            [
                "entry",
                "create",
                "--definition-id",
                "rg_123",
                "--data",
                '{"title": "Foo", "ff_xxx": "value"}',
            ],
        )
        assert result.exit_code != 0
        assert "ff_xxx" in result.output

    def test_values_wrapper_payload_passes_through(self, runner):
        # Canonical shape: ff_* nested under `values`. Must reach the server
        # unchanged so backend can merge into the item aggregate.
        mock_result = {"success": True, "data": {"id": "i_ok"}}
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
                    "entry",
                    "create",
                    "--definition-id",
                    "rg_123",
                    "--data",
                    '{"title": "Foo", "values": {"ff_xxx": "value"}}',
                ],
            )
            assert result.exit_code == 0, result.output
            payload = mock_request.call_args.kwargs["json"]
            assert payload["data"]["values"] == {"ff_xxx": "value"}
            assert payload["data"]["title"] == "Foo"


class TestEntryUpdate:
    def test_update_entry(self, runner):
        mock_result = {"success": True, "data": {"id": "i_001"}}
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
                    "entry",
                    "update",
                    "--entry-id",
                    "i_001",
                    "--data",
                    '{"values": {"status": "done"}}',
                ],
            )
            assert result.exit_code == 0
            assert "i_001" in result.output
            # --note omitted: payload carries no note key.
            payload = mock_request.call_args.kwargs["json"]
            assert "note" not in payload

    def test_update_entry_note_passes_through(self, runner):
        mock_result = {"success": True, "data": {"id": "i_001"}}
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
                    "entry",
                    "update",
                    "--entry-id",
                    "i_001",
                    "--data",
                    '{"values": {"status": "done"}}',
                    "--note",
                    "Updated status after review prep",
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "update"
            # --note is folded into the data object; never a top-level key.
            assert payload["data"]["note"] == "Updated status after review prep"
            assert "note" not in payload

    def test_update_help_mentions_pending_revision(self, runner):
        result = runner.invoke(cli, ["entry", "update", "--help"])
        assert result.exit_code == 0
        assert "pending revision" in result.output.lower()
        assert "review" in result.output.lower()

    def test_update_entry_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "entry",
                "update",
                "--entry-id",
                "i_001",
                "--data",
                '{"values": {"status": "done"}}',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()


class TestEntrySaveDraft:
    def test_save_draft(self, runner):
        mock_result = {"success": True, "data": {"id": "t_789"}}
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
                    "entry",
                    "save-draft",
                    "--task-id",
                    "t_789",
                    "--note",
                    "Prefilled from Q2 report",
                ],
            )
            assert result.exit_code == 0

    def test_save_draft_invokes_draft_mutation_with_values_and_note(self, runner):
        mock_result = {"success": True, "data": {"id": "t_789"}}
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
                    "entry",
                    "save-draft",
                    "--entry-id",
                    "r_abc",
                    "--task-id",
                    "t_789",
                    "--note",
                    "Prefilled from Q2 report",
                    "--data",
                    '{"values": {"ff_approved": true}}',
                ],
            )
            assert result.exit_code == 0
            payload = mock_request.call_args.kwargs["json"]
            assert payload["operation"] == "save_task_draft"
            assert payload["entry_id"] == "r_abc"
            assert payload["task_id"] == "t_789"
            # --note is folded into the data object; never a top-level key.
            assert payload["data"]["note"] == "Prefilled from Q2 report"
            assert "note" not in payload
            assert payload["data"]["values"] == {"ff_approved": True}

    def test_save_draft_missing_note_errors(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock()
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "entry",
                    "save-draft",
                    "--task-id",
                    "t_789",
                ],
            )
            assert result.exit_code != 0
            assert "--note" in result.output
            mock_request.assert_not_called()

    def test_complete_task_removed(self, runner):
        result = runner.invoke(cli, ["entry", "complete-task", "--task-id", "t_789"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_complete_task_gone_from_help(self, runner):
        result = runner.invoke(cli, ["entry", "--help"])
        assert result.exit_code == 0
        assert "complete-task" not in result.output
        assert "save-draft" in result.output


class TestEntryDelete:
    def test_delete_entry_confirmed(self, runner):
        mock_result = {"success": True, "data": {"id": "i_001"}}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
            patch("upscaler_cli.cli.helpers.confirm_destructive", return_value=True),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["entry", "delete", "--entry-id", "i_001"])
            assert result.exit_code == 0

    def test_delete_entry_cancelled(self, runner):
        with patch("upscaler_cli.cli.helpers.confirm_destructive", return_value=False):
            result = runner.invoke(cli, ["entry", "delete", "--entry-id", "i_001"])
            assert "Cancelled" in result.output or result.exit_code == 0

    def test_delete_entry_dry_run(self, runner):
        result = runner.invoke(
            cli,
            [
                "entry",
                "delete",
                "--entry-id",
                "i_001",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()


class TestEntryApiError:
    def test_api_error(self, runner):
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
                    "entry",
                    "create",
                    "--definition-id",
                    "rg_123",
                    "--data",
                    '{"title": "Fail"}',
                ],
            )
            assert result.exit_code != 0
