"""Shared fixtures for CLI command tests.

Every test that invokes a command has to stand up the same three patches:
CLIConfig (for the resolved server URL), TokenStore, and UpscalerClient. That
block was copy-pasted into roughly 145 tests across this directory, so the three
import paths are effectively hard-coded 145 times and moving any of them means
editing every one.

`mock_request` collapses that to a single fixture returning the AsyncMock the
command's HTTP call resolves to, so a test asserts on the request it made and
nothing else.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@contextmanager
def _patched_client(response):
    with (
        patch("upscaler_cli.config.CLIConfig") as config,
        patch("upscaler_cli.auth.token_store.TokenStore"),
        patch("upscaler_cli.client.UpscalerClient") as client,
    ):
        config.return_value.resolve_server_url.return_value = "https://api.example.com"
        request = AsyncMock(return_value=response)
        client.return_value.request = request
        yield request


@pytest.fixture
def mock_request():
    """Patch the client stack and yield the AsyncMock standing in for the call.

    Usage:
        with mock_request({"success": True, "data": {...}}) as request:
            result = runner.invoke(cli, [...])
            assert request.call_args.args[1] == "/api/v1/assets/rg_1"
    """
    return _patched_client
