"""Tests for `upscaler files sign-get` (A093 T007).

The command resolves a signed download URL from GET /api/v1/files/sign-get and
prints the URL (human) or the envelope (--json). AV/not-found refusals surface
as a non-zero exit via the client's APIError.
"""

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli
from upscaler_cli.errors import APIError


@pytest.fixture
def runner():
    return CliRunner()


def _ok():
    return {"success": True, "data": {"url": "https://s3/download?sig=abc"}, "error": None}


class TestFilesSignGet:
    def test_prints_url_in_human_mode(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok())

            result = runner.invoke(
                cli, ["files", "sign-get", "--key", "k", "--name", "f.pdf"]
            )

            assert result.exit_code == 0
            assert result.output.strip() == "https://s3/download?sig=abc"
            call = MockClient.return_value.request.call_args
            assert call.args[0] == "GET"
            assert call.args[1] == "/api/v1/files/sign-get"
            assert call.kwargs["params"] == {"key": "k", "name": "f.pdf"}

    def test_json_mode_prints_envelope(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok())

            result = runner.invoke(
                cli, ["--json", "files", "sign-get", "--key", "k", "--name", "f.pdf"]
            )
            assert result.exit_code == 0
            assert '"url"' in result.output

    def test_bucket_forwarded(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok())

            runner.invoke(
                cli,
                ["files", "sign-get", "--key", "k", "--name", "f.pdf", "--bucket", "b1"],
            )
            call = MockClient.return_value.request.call_args
            assert call.kwargs["params"]["bucket"] == "b1"

    def test_av_refusal_exits_non_zero(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=APIError("file is flagged infected", 403)
            )

            result = runner.invoke(
                cli, ["files", "sign-get", "--key", "k", "--name", "f.pdf"]
            )
            assert result.exit_code != 0
            assert "infected" in result.output
