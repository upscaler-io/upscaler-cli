"""Tests for the low-level `upscaler files presign` CLI command.

The command is the escape hatch from A076 FR-007: it prints the raw presign
envelope as JSON so scripts can drive the upload themselves. The CLI's only
responsibility is to forward the two flags to POST /api/v1/files/presign
and print the response.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def _envelope():
    return {
        "success": True,
        "data": {
            "uid": "i_abc123",
            "url": "https://test-org.s3.eu-west-1.amazonaws.com",
            "fields": {
                "key": "i_abc123",
                "Policy": "<policy>",
                "Tagging": (
                    "<Tagging><TagSet><Tag><Key>lifecycle</Key>"
                    "<Value>pending</Value></Tag></TagSet></Tagging>"
                ),
            },
            "bucket": "test-org",
            "expires_in": 120,
        },
        "error": None,
    }


class TestFilesPresign:
    def test_prints_envelope_and_exits_zero_on_success(self, runner):
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=_envelope())

            result = runner.invoke(
                cli,
                [
                    "files",
                    "presign",
                    "--file-name",
                    "report.pdf",
                    "--content-type",
                    "application/pdf",
                    "--asset-id",
                    "i_target",
                ],
            )

            assert result.exit_code == 0
            body = json.loads(result.output)
            assert body["success"] is True
            assert body["data"]["uid"] == "i_abc123"
            # The lifecycle=pending tag is what makes the envelope correct:
            # downstream scripts rely on this to know an orphan-cleanup tag
            # will be applied at upload time.
            assert "lifecycle" in body["data"]["fields"]["Tagging"]
            assert "pending" in body["data"]["fields"]["Tagging"]

            # Confirm the HTTP call shape matches the REST contract.
            # asset_id is required by the backend so it can run a per-asset
            # write-permission check before minting the presign envelope.
            call_args = MockClient.return_value.request.call_args
            assert call_args.args[0] == "POST"
            assert call_args.args[1] == "/api/v1/files/presign"
            assert call_args.kwargs["json"] == {
                "file_name": "report.pdf",
                "content_type": "application/pdf",
                "asset_id": "i_target",
            }

    def test_server_failure_envelope_exits_non_zero(self, runner):
        # The REST endpoint can return success=false (e.g. backend refused to
        # mint the presign: auth check failed, S3 unavailable). The CLI still
        # prints the envelope so the caller sees the error field, but exits
        # non-zero so scripts can detect failure via $?.
        failure = {
            "success": False,
            "data": None,
            "error": "Failed to obtain presigned URL",
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(return_value=failure)

            result = runner.invoke(
                cli,
                [
                    "files",
                    "presign",
                    "--file-name",
                    "report.pdf",
                    "--content-type",
                    "application/pdf",
                    "--asset-id",
                    "i_target",
                ],
            )

            assert result.exit_code == 1
            body = json.loads(result.output)
            assert body["success"] is False
            assert body["error"] == "Failed to obtain presigned URL"

    def test_http_exception_exits_non_zero(self, runner):
        # If the HTTP client throws (network down, auth refused, server 5xx),
        # the CLI must route through handle_error rather than crash with a
        # bare stack trace. Exit non-zero so scripts can detect failure.
        with (
            patch("upscaler_cli.config.CLIConfig") as MC,
            patch("upscaler_cli.auth.token_store.TokenStore"),
            patch("upscaler_cli.client.UpscalerClient") as MockClient,
        ):
            MC.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockClient.return_value.request = AsyncMock(
                side_effect=RuntimeError("Connection refused"),
            )

            result = runner.invoke(
                cli,
                [
                    "files",
                    "presign",
                    "--file-name",
                    "report.pdf",
                    "--content-type",
                    "application/pdf",
                    "--asset-id",
                    "i_target",
                ],
            )

            assert result.exit_code != 0

    def test_missing_asset_id_fails_usage_error(self, runner):
        # The backend's POST /api/v1/files/presign rejects requests without
        # asset_id (HTTP 422). The CLI fails fast at parse time so the user
        # sees the missing flag instead of a generic 422 from the server.
        result = runner.invoke(
            cli,
            [
                "files",
                "presign",
                "--file-name",
                "report.pdf",
                "--content-type",
                "application/pdf",
            ],
        )

        assert result.exit_code != 0
        assert "--asset-id" in result.output
