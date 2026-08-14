"""Tests for automation CLI commands."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _patched_client(return_value):
    """Patch CLIConfig + TokenStore + UpscalerClient so a single request mock is asserted."""
    mock_request = AsyncMock(return_value=return_value)

    config_patch = patch("upscaler_cli.config.CLIConfig")
    store_patch = patch("upscaler_cli.auth.token_store.TokenStore")
    client_patch = patch("upscaler_cli.client.UpscalerClient")

    return config_patch, store_patch, client_patch, mock_request


class TestAutomationList:
    def test_list_json(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {
                "success": True,
                "data": [{"id": "auto_1", "title": "A", "enabled": True}],
                "metadata": {"total_count": 1, "has_more": False},
            }
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "automation", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "list"

    def test_list_for_asset(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": []}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["--json", "automation", "list", "--asset-id", "d_xyz"]
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "list_for_asset"
        assert payload["asset_id"] == "d_xyz"

    def test_list_upcoming(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": []}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "automation", "list", "--upcoming"])
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "list_upcoming"

    def test_list_upcoming_and_asset_id_is_mutually_exclusive(self, runner):
        result = runner.invoke(
            cli,
            ["automation", "list", "--upcoming", "--asset-id", "d_xyz"],
        )
        assert result.exit_code != 0


class TestAutomationGet:
    def test_get(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {"id": "auto_1", "title": "X"}}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "automation", "get", "auto_1"])
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload == {"action": "get", "id": "auto_1"}


class TestAutomationLifecycle:
    @pytest.mark.parametrize("action", ["enable", "disable", "run"])
    def test_lifecycle_action(self, runner, action):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {"id": "auto_1"}}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "automation", action, "auto_1"])
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == action
        assert payload["id"] == "auto_1"


class TestAutomationCreate:
    def test_create_with_inline_data(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {"id": "auto_new"}}
        )
        body = json.dumps(
            {
                "title": "Weekly",
                "trigger": {
                    "type": "schedule",
                    "schedule": {"cron": "0 9 * * 1", "timezone": "UTC"},
                },
                "target": {"type": "asset", "asset": {"id": "d_x", "type": "document"}},
                "action": {
                    "type": "createTodo",
                    "createTodo": {"title": "Review", "assignees": []},
                },
            }
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["--json", "automation", "create", "--data", body]
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "create"
        assert payload["data"]["title"] == "Weekly"

    def test_create_dry_run(self, runner):
        body = json.dumps({"title": "X"})
        result = runner.invoke(
            cli, ["--json", "automation", "create", "--data", body, "--dry-run"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["payload"]["action"] == "create"


class TestAutomationRuns:
    def test_runs(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": []}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["--json", "automation", "runs", "auto_1", "--limit", "5"]
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "list_runs"
        assert payload["limit"] == 5


class TestAutomationEnvelopeErrors:
    def test_failure_envelope_surfaces_error(self, runner):
        """A 200 {"success": false} envelope (e.g. unresolved org) must fail
        loudly via execute_rest_action, not render an empty summary."""
        config_p, store_p, client_p, mock_request = _patched_client(
            {
                "success": False,
                "error": {"message": "Organization context required"},
                "data": [],
            }
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["automation", "list"])
        assert result.exit_code != 0
        assert "Organization context required" in result.output
