"""Tests for `upscaler files download` (A093 T008).

The command resolves a signed URL then streams the bytes to --output or
--stdout. The signed-URL resolution (client.request) and the byte stream
(httpx.stream) are both mocked.
"""

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli
from upscaler_cli.errors import APIError


@pytest.fixture
def runner():
    return CliRunner()


def _ok_url():
    return {"success": True, "data": {"url": "https://s3/download?sig=abc"}, "error": None}


class _FakeStream:
    """Context manager mimicking httpx.stream(...) with byte chunks."""

    def __init__(self, chunks, content_type="application/pdf"):
        self._chunks = chunks
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self, size):
        for c in self._chunks:
            yield c


class TestFilesDownload:
    def test_writes_bytes_to_output_file(self, runner, tmp_path):
        out = tmp_path / "report.pdf"
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
            patch("httpx.stream", return_value=_FakeStream([b"abcd", b"efgh"])),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok_url())
            MockClient.return_value.verify_ssl = True

            result = runner.invoke(
                cli,
                ["files", "download", "--key", "k", "--name", "f.pdf", "--output", str(out)],
            )

        assert result.exit_code == 0, result.output
        assert out.read_bytes() == b"abcdefgh"
        assert "8 bytes" in result.output
        assert "application/pdf" in result.output

    def test_stdout_streams_bytes(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
            patch("httpx.stream", return_value=_FakeStream([b"hello"])),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok_url())
            MockClient.return_value.verify_ssl = True

            result = runner.invoke(
                cli, ["files", "download", "--key", "k", "--name", "f.pdf", "--stdout"]
            )

        assert result.exit_code == 0, result.output
        # The byte payload lands on stdout (CliRunner captures it as text).
        assert "hello" in result.output

    def test_refuses_existing_output_without_force(self, runner, tmp_path):
        out = tmp_path / "exists.pdf"
        out.write_bytes(b"old")
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok_url())

            result = runner.invoke(
                cli,
                ["files", "download", "--key", "k", "--name", "f.pdf", "--output", str(out)],
            )

        assert result.exit_code != 0
        assert "overwrite" in result.output.lower()
        assert out.read_bytes() == b"old"

    def test_force_overwrites_existing_output(self, runner, tmp_path):
        out = tmp_path / "exists.pdf"
        out.write_bytes(b"old")
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
            patch("httpx.stream", return_value=_FakeStream([b"new-bytes"])),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_ok_url())
            MockClient.return_value.verify_ssl = True

            result = runner.invoke(
                cli,
                [
                    "files", "download", "--key", "k", "--name", "f.pdf",
                    "--output", str(out), "--force",
                ],
            )

        assert result.exit_code == 0, result.output
        assert out.read_bytes() == b"new-bytes"

    def test_requires_exactly_one_sink(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient"),
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            # Neither --output nor --stdout
            result = runner.invoke(cli, ["files", "download", "--key", "k", "--name", "f.pdf"])
        assert result.exit_code != 0
        assert "exactly one" in result.output.lower()

    def test_av_refusal_surfaced(self, runner, tmp_path):
        out = tmp_path / "r.pdf"
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
                cli,
                ["files", "download", "--key", "k", "--name", "f.pdf", "--output", str(out)],
            )

        assert result.exit_code != 0
        assert "infected" in result.output
        assert not out.exists()
