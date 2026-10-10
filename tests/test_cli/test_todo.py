"""Tests for todo CLI commands."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _mock_execution(module_path="upscaler_cli.cli.todo"):
    """Return context managers that mock CLIConfig, TokenStore, UpscalerClient."""
    patches = {
        "config": patch(f"{module_path}.CLIConfig"),
        "store": patch(f"{module_path}.TokenStore"),
        "client": patch(f"{module_path}.UpscalerClient"),
    }
    return patches


def _setup_mocks(mock_config, mock_client_cls, return_value):
    """Configure standard mock behaviour for _execute_* helpers."""
    mock_config.return_value.resolve_server_url.return_value = "https://api.example.com"
    mock_client_cls.return_value.request = AsyncMock(return_value=return_value)


class TestTodoCreate:
    def test_create_todo(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_1", "title": "Test"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["todo", "create", "--title", "Test"])
            assert result.exit_code == 0
            assert "todo_1" in result.output

    def test_create_todo_failure_envelope_surfaces_error(self, runner):
        """A 200 {"success": false} envelope must fail loudly, not print an
        empty 'Todo created: —'."""
        mock_result = {
            "success": False,
            "error": {"message": "Organization context required"},
            "data": {},
        }
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["todo", "create", "--title", "Test"])
            assert result.exit_code != 0
            assert "Organization context required" in result.output

    def test_create_todo_with_assignee_and_due(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_2", "title": "Due task"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, [
                "todo", "create",
                "--title", "Due task",
                "--assignee", "user_1",
                "--due", "2026-04-01",
            ])
            assert result.exit_code == 0
            assert "todo_2" in result.output
            # Verify the payload includes assignees and dueDateTime
            call_kwargs = mock_request.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload["data"]["assignees"] == ["user_1"]
            assert payload["data"]["dueDateTime"] == "2026-04-01"

    def test_create_todo_dry_run(self, runner):
        result = runner.invoke(cli, ["todo", "create", "--title", "Test", "--dry-run"])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()

    def test_create_todo_json_mode(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_1"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "todo", "create", "--title", "Test"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True

    def test_create_todo_dry_run_json_mode(self, runner):
        result = runner.invoke(cli, ["--json", "todo", "create", "--title", "Test", "--dry-run"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["operation"] == "create"

    def test_create_todo_missing_title(self, runner):
        result = runner.invoke(cli, ["todo", "create"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_create_todo_with_bookmark_url(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_3", "title": "BM"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, [
                "todo", "create", "--title", "BM", "--bookmark-url", "/document/d_1",
            ])
            assert result.exit_code == 0
            call = mock_request.call_args
            payload = call.kwargs.get("json") or call[1].get("json")
            assert payload["data"]["bookmarkUrl"] == "/document/d_1"

    def test_create_todo_without_bookmark_url_omits_key(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_4", "title": "NoBM"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["todo", "create", "--title", "NoBM"])
            assert result.exit_code == 0
            call = mock_request.call_args
            payload = call.kwargs.get("json") or call[1].get("json")
            assert "bookmarkUrl" not in payload["data"]

    def test_create_todo_bookmark_dry_run_preview(self, runner):
        result = runner.invoke(cli, [
            "todo", "create", "--title", "BM", "--bookmark-url", "/document/d_1", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "/document/d_1" in result.output

    def test_create_todo_with_description(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_5", "title": "Desc"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            mock_request = AsyncMock(return_value=mock_result)
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, [
                "todo", "create", "--title", "Desc", "--description", "Body **text**",
            ])
            assert result.exit_code == 0
            call = mock_request.call_args
            payload = call.kwargs.get("json") or call[1].get("json")
            assert payload["data"]["description"] == "Body **text**"

    def test_create_todo_without_description_omits_key(self, runner):
        result = runner.invoke(cli, ["--json", "todo", "create", "--title", "T", "--dry-run"])
        assert result.exit_code == 0
        assert "description" not in json.loads(result.output)["payload"]["data"]

    def test_create_todo_bookmark_in_help(self, runner):
        result = runner.invoke(cli, ["todo", "create", "--help"])
        assert result.exit_code == 0
        assert "--bookmark-url" in result.output
        assert "in-app path" in result.output.lower()


class TestTodoUpdate:
    def test_update_todo(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_1", "title": "Updated"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, [
                "todo", "update", "todo_1", "--title", "Updated",
            ])
            assert result.exit_code == 0
            assert "todo_1" in result.output

    def test_update_todo_with_description(self, runner):
        result = runner.invoke(cli, [
            "--json", "todo", "update", "todo_1", "--description", "New body", "--dry-run",
        ])
        assert result.exit_code == 0
        assert json.loads(result.output)["payload"]["data"] == {"description": "New body"}

    def test_update_todo_dry_run(self, runner):
        result = runner.invoke(cli, [
            "todo", "update", "todo_1", "--title", "Updated", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()


class TestTodoClose:
    def test_close_todo(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_1", "status": "closed"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["todo", "close", "todo_1"])
            assert result.exit_code == 0

    def test_close_todo_json_mode(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_1", "status": "closed"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "todo", "close", "todo_1"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True


class TestTodoReopen:
    def test_reopen_todo(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_1", "status": "open"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["todo", "reopen", "todo_1"])
            assert result.exit_code == 0


class TestTodoDelete:
    def test_delete_todo_confirmed(self, runner):
        mock_result = {"success": True, "data": {"id": "todo_1"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient, \
             patch("upscaler_cli.cli.helpers.confirm_destructive", return_value=True):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["todo", "delete", "todo_1"])
            assert result.exit_code == 0

    def test_delete_todo_cancelled(self, runner):
        with patch("upscaler_cli.cli.helpers.confirm_destructive", return_value=False):
            result = runner.invoke(cli, ["todo", "delete", "todo_1"])
            assert "Cancelled" in result.output or result.exit_code == 0

    def test_delete_todo_dry_run(self, runner):
        result = runner.invoke(cli, ["todo", "delete", "todo_1", "--dry-run"])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()


class TestTodoApiError:
    def test_api_error_human_mode(self, runner):
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=RuntimeError("Network failure")
            )
            result = runner.invoke(cli, ["todo", "create", "--title", "Fail"])
            assert result.exit_code != 0

    def test_api_error_json_mode(self, runner):
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=RuntimeError("Network failure")
            )
            result = runner.invoke(cli, ["--json", "todo", "create", "--title", "Fail"])
            assert result.exit_code != 0


class TestTodoPriority:
    """A110 FR-010: priority on create and update."""

    def _invoke(self, runner, args):
        mock_result = {"success": True, "data": {"id": "todo_1", "title": "Test"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, args)
            return result, MockClient.return_value.request

    def test_create_sends_priority(self, runner):
        result, request = self._invoke(
            runner, ["todo", "create", "--title", "T", "--priority", "URGENT"]
        )
        assert result.exit_code == 0
        assert request.call_args.kwargs["json"]["data"]["priority"] == "URGENT"

    def test_update_sends_priority(self, runner):
        result, request = self._invoke(
            runner, ["todo", "update", "todo_1", "--priority", "high"]
        )
        assert result.exit_code == 0
        assert request.call_args.kwargs["json"]["data"] == {"priority": "HIGH"}

    def test_invalid_priority_rejected_before_any_request(self, runner):
        result, request = self._invoke(
            runner, ["todo", "create", "--title", "T", "--priority", "CRITICAL"]
        )
        assert result.exit_code != 0
        assert "urgent" in result.output.lower() and "low" in result.output.lower()
        request.assert_not_called()

    def test_omitted_priority_sends_no_key(self, runner):
        result, request = self._invoke(runner, ["todo", "create", "--title", "T"])
        assert result.exit_code == 0
        assert "priority" not in request.call_args.kwargs["json"]["data"]


class TestTodoLabels:
    """A110 FR-013 AC2: repeatable --label on create and update."""

    def _invoke(self, runner, args):
        mock_result = {"success": True, "data": {"id": "todo_1", "title": "Test"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, args)
            return result, MockClient.return_value.request

    def test_create_sends_every_label(self, runner):
        result, request = self._invoke(
            runner,
            ["todo", "create", "--title", "T", "--label", "tg_a", "--label", "tg_b"],
        )
        assert result.exit_code == 0
        assert request.call_args.kwargs["json"]["data"]["labels"] == ["tg_a", "tg_b"]

    def test_update_sends_labels(self, runner):
        result, request = self._invoke(runner, ["todo", "update", "todo_1", "--label", "tg_a"])
        assert result.exit_code == 0
        assert request.call_args.kwargs["json"]["data"] == {"labels": ["tg_a"]}

    def test_omitted_label_sends_no_key(self, runner):
        result, request = self._invoke(runner, ["todo", "create", "--title", "T"])
        assert result.exit_code == 0
        assert "labels" not in request.call_args.kwargs["json"]["data"]


class TestTodoBlock:
    """A110 FR-019 AC2: `todo block` and `todo unblock`."""

    def _invoke(self, runner, args):
        mock_result = {"success": True, "data": {"id": "todo_1", "title": "Test"}}
        with patch("upscaler_cli.config.CLIConfig") as MC, \
             patch("upscaler_cli.auth.token_store.TokenStore"), \
             patch("upscaler_cli.client.UpscalerClient") as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, args)
            return result, MockClient.return_value.request

    def test_block_sends_the_operation_and_reason(self, runner):
        result, request = self._invoke(
            runner, ["todo", "block", "todo_1", "--reason", "waiting on supplier"]
        )
        assert result.exit_code == 0
        assert request.call_args.kwargs["json"] == {
            "operation": "block",
            "id": "todo_1",
            "data": {"reason": "waiting on supplier"},
        }

    def test_block_requires_a_reason(self, runner):
        result, request = self._invoke(runner, ["todo", "block", "todo_1"])
        assert result.exit_code != 0
        request.assert_not_called()

    def test_unblock_sends_the_operation(self, runner):
        result, request = self._invoke(runner, ["todo", "unblock", "todo_1"])
        assert result.exit_code == 0
        assert request.call_args.kwargs["json"] == {"operation": "unblock", "id": "todo_1"}
