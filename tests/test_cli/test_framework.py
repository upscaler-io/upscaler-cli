"""Tests for compliance framework CLI commands."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _patched_client(return_value):
    mock_request = AsyncMock(return_value=return_value)
    config_patch = patch("upscaler_cli.config.CLIConfig")
    store_patch = patch("upscaler_cli.auth.token_store.TokenStore")
    client_patch = patch("upscaler_cli.client.UpscalerClient")
    return config_patch, store_patch, client_patch, mock_request


class TestFrameworkReads:
    def test_list_installed(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": []}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(cli, ["--json", "framework", "list-installed"])
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload == {"action": "list_installed"}

    def test_get_installed(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {"framework": {"id": "iso27001"}}}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["--json", "framework", "get-installed", "iso27001"]
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload == {"action": "get_installed", "framework_id": "iso27001"}

    def test_list_contributions(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": []}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["--json", "framework", "list-contributions", "--asset-id", "d_xyz"]
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "list_asset_contributions"
        assert payload["asset_id"] == "d_xyz"

    def test_list_requirement_contributions(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {"documents": [], "records": []}}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "framework",
                    "list-requirement-contributions",
                    "--framework-id",
                    "iso27001",
                    "--requirement-id",
                    "A.5.1",
                ],
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "list_requirement_contributions"
        assert payload["framework_id"] == "iso27001"
        assert payload["requirement_id"] == "A.5.1"

    def test_list_test_bindings(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": []}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli, ["--json", "framework", "list-test-bindings", "--asset-id", "d_xyz"]
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "list_asset_test_bindings"


class TestFrameworkBindings:
    def test_bind(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {}}
        )
        body = json.dumps(
            {
                "role": "iso27001:soa",
                "target": {"kind": "register", "registerId": "rg_xyz"},
                "fields": {"identifier": "ref"},
            }
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "framework",
                    "bind",
                    "--framework-id",
                    "iso27001",
                    "--data",
                    body,
                ],
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "create_binding"
        assert payload["framework_id"] == "iso27001"
        assert payload["data"]["role"] == "iso27001:soa"


class TestFrameworkTests:
    def test_set_test_binding(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {}}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "framework",
                    "set-test-binding",
                    "--framework-id",
                    "iso27001",
                    "--requirement-id",
                    "A.5.1",
                    "--test-id",
                    "exists-1",
                    "--asset-id",
                    "d_xyz",
                ],
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "set_test_binding"
        assert payload["test_id"] == "exists-1"
        assert payload["asset_id"] == "d_xyz"

    def test_evaluate(self, runner):
        config_p, store_p, client_p, mock_request = _patched_client(
            {"success": True, "data": {}}
        )
        with config_p as MC, store_p, client_p as MockClient:
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = mock_request
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "framework",
                    "evaluate",
                    "--framework-id",
                    "iso27001",
                    "--requirement-id",
                    "A.5.1",
                ],
            )
        assert result.exit_code == 0
        payload = mock_request.call_args.kwargs["json"]
        assert payload["action"] == "evaluate_tests"
        # No test_id when not provided
        assert "test_id" not in payload


class TestFrameworkEnvelopeErrors:
    def test_failure_envelope_surfaces_error(self, runner):
        """A 200 {"success": false} envelope (e.g. unresolved org) must fail
        loudly via execute_rest_action, not render an empty result."""
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
            result = runner.invoke(cli, ["framework", "list-installed"])
        assert result.exit_code != 0
        assert "Organization context required" in result.output
