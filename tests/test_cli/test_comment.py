"""Tests for the `upscaler comment` command group (A093 T016).

Local validation (allow-list, content length, mention format) must fail fast
before any HTTP call. Happy paths forward the right payload/params.
"""

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _ok(data):
    return {"success": True, "data": data, "error": None}


class TestCommentList:
    def test_renders_comments(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                return_value=_ok(
                    {
                        "comments": [
                            {
                                "content": "looks good",
                                "createdAt": "2026-07-14",
                                "author": {"name": "Kong"},
                            }
                        ],
                        "totalCount": 1,
                    }
                )
            )
            result = runner.invoke(
                cli,
                ["comment", "list", "--asset-id", "to_1", "--asset-type", "todo"],
            )
        assert result.exit_code == 0, result.output
        assert "Kong" in result.output
        assert "looks good" in result.output
        call = MockClient.return_value.request.call_args
        assert call.args[1] == "/api/v1/comments"
        assert call.kwargs["params"]["asset_id"] == "to_1"

    def test_disallowed_type_fails_before_http(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(
                cli,
                ["comment", "list", "--asset-id", "d_1", "--asset-type", "document"],
            )
        assert result.exit_code != 0
        assert "not supported" in result.output
        MockClient.return_value.request.assert_not_called()


class TestCommentAdd:
    def test_add_forwards_payload_with_mentions(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok({"id": "co_new"}))
            result = runner.invoke(
                cli,
                [
                    "comment", "add", "--asset-id", "to_1", "--asset-type", "todo",
                    "--content", "done", "--mention", "member::m1", "--mention", "group::g2",
                ],
            )
        assert result.exit_code == 0, result.output
        payload = MockClient.return_value.request.call_args.kwargs["json"]
        assert payload["mentions"] == ["member::m1", "group::g2"]
        assert payload["content"] == "done"

    def test_malformed_mention_fails_before_http(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(
                cli,
                [
                    "comment", "add", "--asset-id", "to_1", "--asset-type", "todo",
                    "--content", "hi", "--mention", "m1",
                ],
            )
        assert result.exit_code != 0
        assert "mention" in result.output.lower()
        MockClient.return_value.request.assert_not_called()

    def test_overlong_content_fails_before_http(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(
                cli,
                [
                    "comment", "add", "--asset-id", "to_1", "--asset-type", "todo",
                    "--content", "x" * 2001,
                ],
            )
        assert result.exit_code != 0
        assert "exceeds" in result.output.lower()
        MockClient.return_value.request.assert_not_called()


class TestCommentEdit:
    def test_edit_without_mentions_omits_key(self, runner):
        """Omitted --mention must not appear in the payload (stored list unchanged)."""
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok({"id": "co_1"}))
            result = runner.invoke(
                cli,
                ["comment", "edit", "--comment-id", "co_1", "--content", "revised"],
            )
        assert result.exit_code == 0, result.output
        call = MockClient.return_value.request.call_args
        assert call.args[0] == "POST"
        assert call.args[1] == "/api/v1/comments"
        payload = call.kwargs["json"]
        assert payload == {"action": "edit", "comment_id": "co_1", "content": "revised"}
        assert "mentions" not in payload

    def test_edit_with_mentions_replaces(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok({"id": "co_1"}))
            result = runner.invoke(
                cli,
                [
                    "comment", "edit", "--comment-id", "co_1", "--content", "revised",
                    "--mention", "member::m1", "--mention", "group::g2",
                ],
            )
        assert result.exit_code == 0, result.output
        payload = MockClient.return_value.request.call_args.kwargs["json"]
        assert payload["mentions"] == ["member::m1", "group::g2"]

    def test_edit_clear_mentions_sends_empty_list(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok({"id": "co_1"}))
            result = runner.invoke(
                cli,
                [
                    "comment", "edit", "--comment-id", "co_1", "--content", "revised",
                    "--clear-mentions",
                ],
            )
        assert result.exit_code == 0, result.output
        payload = MockClient.return_value.request.call_args.kwargs["json"]
        assert payload["mentions"] == []

    def test_mention_and_clear_mentions_are_exclusive(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(
                cli,
                [
                    "comment", "edit", "--comment-id", "co_1", "--content", "x",
                    "--mention", "member::m1", "--clear-mentions",
                ],
            )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output
        MockClient.return_value.request.assert_not_called()

    def test_edit_malformed_mention_fails_before_http(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(
                cli,
                [
                    "comment", "edit", "--comment-id", "co_1", "--content", "x",
                    "--mention", "m1",
                ],
            )
        assert result.exit_code != 0
        MockClient.return_value.request.assert_not_called()

    def test_edit_overlong_content_fails_before_http(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(
                cli,
                ["comment", "edit", "--comment-id", "co_1", "--content", "x" * 2001],
            )
        assert result.exit_code != 0
        assert "exceeds" in result.output.lower()
        MockClient.return_value.request.assert_not_called()


class TestCommentDelete:
    def test_delete_sends_action_payload(self, runner):
        """json_mode off but non-tty: confirm_destructive auto-skips the prompt."""
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                return_value=_ok({"id": "co_1", "deleted": True})
            )
            result = runner.invoke(cli, ["comment", "delete", "co_1"])
        assert result.exit_code == 0, result.output
        payload = MockClient.return_value.request.call_args.kwargs["json"]
        assert payload == {"action": "delete", "comment_id": "co_1"}

    def test_delete_dry_run_makes_no_request(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(cli, ["comment", "delete", "co_1", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "dry" in result.output.lower()
        MockClient.return_value.request.assert_not_called()

    def test_delete_cancelled_when_confirm_declined(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
            patch("upscaler_cli.cli.helpers.confirm_destructive", return_value=False),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock()
            result = runner.invoke(cli, ["comment", "delete", "co_1"])
        assert "Cancelled" in result.output
        MockClient.return_value.request.assert_not_called()
