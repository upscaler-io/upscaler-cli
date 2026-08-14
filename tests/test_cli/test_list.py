"""Tests for list CLI commands."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestListDefinitions:
    def test_list_definitions_table(self, runner):
        mock_result = {
            "success": True,
            "data": [
                {"id": "rg_1", "title": "Safety Register", "type": "register"},
                {"id": "rc_1", "title": "Audit Record", "type": "record"},
            ],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["list", "definitions"])
            assert result.exit_code == 0
            assert "Safety Register" in result.output
            assert "Audit Record" in result.output

    def test_list_definitions_json(self, runner):
        mock_result = {
            "success": True,
            "data": [{"id": "rg_1", "title": "Safety Register", "type": "register"}],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "list", "definitions"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True

    def test_list_definitions_empty(self, runner):
        mock_result = {"success": True, "data": []}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["list", "definitions"])
            assert "No results" in result.output

    def test_list_definitions_pagination(self, runner):
        # definitions now paginate like entries (--limit/--offset), forwarded to
        # the list endpoint.
        mock_result = {"success": True, "data": []}
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(
                cli, ["list", "definitions", "--limit", "50", "--offset", "100"]
            )
            assert result.exit_code == 0
            params = MockClient.return_value.request.call_args.kwargs["params"]
            assert params["limit"] == 50
            assert params["offset"] == 100


class TestListEntries:
    def test_list_entries_with_definition_id(self, runner):
        mock_result = {
            "success": True,
            "data": [
                {"id": "e_1", "title": "Entry One", "status": "active"},
                {"id": "e_2", "title": "Entry Two", "status": "draft"},
            ],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["list", "entries", "--definition-id", "rg_123"])
            assert result.exit_code == 0
            assert "Entry One" in result.output

    def test_list_entries_requires_definition_id(self, runner):
        result = runner.invoke(cli, ["list", "entries"])
        assert result.exit_code != 0

    def test_list_entries_json(self, runner):
        mock_result = {
            "success": True,
            "data": [{"id": "e_1", "title": "Entry One", "status": "active"}],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "list", "entries", "--definition-id", "rg_123"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True

    def test_list_entries_filter_auto_prefixes_values(self, runner):
        """--filter status=open should become values.status=open (auto-prefix)
        only when key is not a known system field. `status` itself IS a
        system field, so it should NOT be prefixed."""
        mock_result = {"success": True, "data": []}
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
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--filter",
                    "status=open",
                    "--filter",
                    "severity=high,medium",
                ],
            )
            assert result.exit_code == 0, result.output
            call_kwargs = MockClient.return_value.request.call_args.kwargs
            params = call_kwargs["params"]
            filters = json.loads(params["filters"])
            assert filters["status"] == "open"
            assert filters["values.severity"] == ["high", "medium"]

    def test_list_entries_filter_explicit_values_prefix(self, runner):
        mock_result = {"success": True, "data": []}
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
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--filter",
                    "values.owner_id=u_abc",
                ],
            )
            assert result.exit_code == 0, result.output
            params = MockClient.return_value.request.call_args.kwargs["params"]
            filters = json.loads(params["filters"])
            assert filters == {"values.owner_id": "u_abc"}

    def test_list_entries_sort(self, runner):
        mock_result = {"success": True, "data": []}
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
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--sort",
                    "updatedAt:desc",
                ],
            )
            assert result.exit_code == 0, result.output
            params = MockClient.return_value.request.call_args.kwargs["params"]
            sort = json.loads(params["sort"])
            assert sort == {"dataIndex": "updatedAt", "order": "descend"}

    def test_list_entries_invalid_sort_order(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient"),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            result = runner.invoke(
                cli,
                [
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--sort",
                    "title:bogus",
                ],
            )
            assert result.exit_code != 0
            assert "asc" in result.output.lower() or "desc" in result.output.lower()

    def test_list_entries_include_archived(self, runner):
        mock_result = {"success": True, "data": []}
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
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--include-archived",
                ],
            )
            assert result.exit_code == 0
            params = MockClient.return_value.request.call_args.kwargs["params"]
            filters = json.loads(params["filters"])
            assert filters["includeArchived"] is True

    def test_list_entries_pagination(self, runner):
        mock_result = {"success": True, "data": []}
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
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--limit",
                    "50",
                    "--offset",
                    "10",
                ],
            )
            assert result.exit_code == 0
            params = MockClient.return_value.request.call_args.kwargs["params"]
            assert params["limit"] == 50
            assert params["offset"] == 10

    def test_list_entries_malformed_filter(self, runner):
        result = runner.invoke(
            cli,
            [
                "list",
                "entries",
                "--definition-id",
                "rg_123",
                "--filter",
                "no_equals_sign",
            ],
        )
        assert result.exit_code != 0


class TestListEntriesIncludeValues:
    """Coverage for --include-values, --select-value, --resolve-labels."""

    _SCHEMA = {
        "success": True,
        "data": {
            "schema": {
                "registerId": "rg_123",
                "fields": [
                    {"key": "ff_priority", "label": "Process Priority/Value"},
                    {"key": "ff_owner", "label": "Responsible Owner"},
                ],
            }
        },
    }

    def _entries_response(self, values_per_item):
        return {
            "success": True,
            "data": {
                "items": [
                    {"_id": "i_1", "title": "SaaS Delivery", "values": values_per_item}
                ],
                "total": 1,
            },
        }

    def test_default_behavior_unchanged(self, runner):
        """Without any new flag, params don't include include_values/select_values
        and the response is not rewritten."""
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                return_value={"success": True, "data": {"items": [], "total": 0}}
            )
            result = runner.invoke(
                cli, ["--json", "list", "entries", "--definition-id", "rg_123"]
            )
            assert result.exit_code == 0
            params = MockClient.return_value.request.call_args.kwargs["params"]
            assert "include_values" not in params
            assert "select_values" not in params

    def test_include_values_sets_param(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                return_value=self._entries_response({"ff_priority": "High"})
            )
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--include-values",
                ],
            )
            assert result.exit_code == 0, result.output
            params = MockClient.return_value.request.call_args.kwargs["params"]
            assert params["include_values"] == "true"
            data = json.loads(result.output)
            assert data["data"]["items"][0]["values"] == {"ff_priority": "High"}

    def test_resolve_labels_rewrites_keys(self, runner):
        """--resolve-labels fetches schema then rewrites ff_* keys to labels."""
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=[
                    self._SCHEMA,
                    self._entries_response(
                        {"ff_priority": "High", "ff_owner": "Audrey"}
                    ),
                ]
            )
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--include-values",
                    "--resolve-labels",
                ],
            )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            values = data["data"]["items"][0]["values"]
            assert values == {
                "Process Priority/Value": "High",
                "Responsible Owner": "Audrey",
            }

    def test_select_value_by_label_resolves_to_key(self, runner):
        """--select-value 'Process Priority/Value' translates to ff_priority
        and implies include_values."""
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=[
                    self._SCHEMA,
                    self._entries_response({"ff_priority": "High"}),
                ]
            )
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--select-value",
                    "Process Priority/Value",
                ],
            )
            assert result.exit_code == 0, result.output
            list_call = MockClient.return_value.request.call_args_list[1]
            params = list_call.kwargs["params"]
            assert params["include_values"] == "true"
            assert params["select_values"] == ["ff_priority"]

    def test_fields_csv_resolves_multiple_and_implies_include_values(self, runner):
        """--fields status,owner is a comma-separated alias for repeated
        --select-value: both labels resolve to ff_* keys and include_values is set."""
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=[
                    self._SCHEMA,
                    self._entries_response({"ff_priority": "High", "ff_owner": "Alice"}),
                ]
            )
            result = runner.invoke(
                cli,
                [
                    "--json",
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--fields",
                    "Process Priority/Value, Responsible Owner",
                ],
            )
            assert result.exit_code == 0, result.output
            list_call = MockClient.return_value.request.call_args_list[1]
            params = list_call.kwargs["params"]
            assert params["include_values"] == "true"
            assert params["select_values"] == ["ff_priority", "ff_owner"]

    def test_select_value_unknown_label_errors(self, runner):
        """Unknown label raises BadParameter with the valid labels listed."""
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=self._SCHEMA)
            result = runner.invoke(
                cli,
                [
                    "list",
                    "entries",
                    "--definition-id",
                    "rg_123",
                    "--select-value",
                    "Nonexistent Field",
                ],
            )
            assert result.exit_code != 0
            assert "Nonexistent Field" in result.output
            assert "Process Priority/Value" in result.output


class TestListTodos:
    def test_list_todos_table(self, runner):
        mock_result = {
            "success": True,
            "data": [
                {"id": "t_1", "title": "Review document", "status": "pending"},
            ],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["list", "todos"])
            assert result.exit_code == 0
            assert "Review document" in result.output

    def test_list_todos_json(self, runner):
        mock_result = {
            "success": True,
            "data": [{"id": "t_1", "title": "Review document", "status": "pending"}],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "list", "todos"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True

    def test_list_todos_table_shows_bookmark_flattened(self, runner):
        # A bookmarked todo shows a clean `bookmark` column, not the raw
        # extra dict blob.
        mock_result = {
            "success": True,
            "data": {
                "items": [
                    {
                        "id": "to_1",
                        "title": "Review",
                        "status": "open",
                        "extra": {"bookmarkUrl": "/document/d_1"},
                    }
                ],
                "total": 1,
            },
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["list", "todos"])
            assert result.exit_code == 0
            assert "/document/d_1" in result.output
            assert "bookmark" in result.output.lower()
            # the raw extra dict must not be dumped into a cell
            assert "bookmarkUrl" not in result.output

    def test_list_todos_table_no_bookmark_omits_column(self, runner):
        # When no todo is bookmarked, neither a raw `extra` column nor a
        # `bookmark` column appears (FR-004.2: no empty cells).
        mock_result = {
            "success": True,
            "data": {
                "items": [
                    {"id": "to_1", "title": "Review", "status": "open", "extra": None}
                ],
                "total": 1,
            },
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["list", "todos"])
            assert result.exit_code == 0
            assert "bookmark" not in result.output.lower()
            assert "extra" not in result.output.lower()

    def test_list_todos_json_includes_extra(self, runner):
        mock_result = {
            "success": True,
            "data": {
                "items": [
                    {
                        "id": "to_1",
                        "title": "Review",
                        "extra": {"bookmarkUrl": "/document/d_1"},
                    }
                ],
                "total": 1,
            },
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "list", "todos"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["data"]["items"][0]["extra"]["bookmarkUrl"] == "/document/d_1"

    def test_list_error(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(side_effect=RuntimeError("Unauthorized"))
            result = runner.invoke(cli, ["list", "definitions"])
            assert result.exit_code != 0

    def test_list_failure_envelope_surfaces_error(self, runner):
        """A 200 {"success": false, ...} envelope (e.g. unresolved org) must
        fail loudly, not render the empty data as "No results"."""
        mock_result = {
            "success": False,
            "error": {"error_code": "VALIDATION_ERROR", "message": "Organization context required"},
            "data": [],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["list", "todos"])
            assert result.exit_code != 0
            assert "Organization context required" in result.output
            assert "No results" not in result.output

    def test_list_failure_envelope_json_mode(self, runner):
        mock_result = {
            "success": False,
            "error": {"error_code": "VALIDATION_ERROR", "message": "Organization context required"},
            "data": [],
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=mock_result)
            result = runner.invoke(cli, ["--json", "list", "todos"])
            assert result.exit_code != 0
            assert "Organization context required" in result.output
