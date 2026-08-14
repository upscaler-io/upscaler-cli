"""Shared fixtures for live integration tests against staging/dev.

These tests hit a REAL REST API (the `dev` profile points at staging,
https://ai.stg.upscaler.app). They are double-gated:

  1. UPSCALER_INTEGRATION_TEST=1 must be set (per-module `pytestmark`).
  2. The selected profile must be authenticated AND resolve to the staging host;
     otherwise the test skips with an actionable message.

Run them with:

    UPSCALER_INTEGRATION_TEST=1 pytest tests/test_integration -v

Prerequisite: log in once for the profile under test, e.g.

    upscaler --profile dev login

Override the profile with UPSCALER_INTEGRATION_PROFILE (defaults to `dev`).
"""

import json
import os
from urllib.parse import urlparse

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.main import cli
from upscaler_cli.config import CLIConfig

# Hostnames we consider non-prod and safe to run live (incl. destructive) tests
# against: staging plus the local dev server. Matched by hostname so trailing
# slashes / scheme differences don't matter. Extend per-run with a comma list in
# UPSCALER_INTEGRATION_ALLOW_URLS. Anything else (notably prod) is refused.
_NONPROD_HOSTS = {"ai.stg.upscaler.app", "ai.localhost", "localhost", "127.0.0.1"}


def _is_allowed_server(url):
    """True if `url` is a known non-prod host or explicitly allow-listed."""
    extra = {
        u.strip()
        for u in os.environ.get("UPSCALER_INTEGRATION_ALLOW_URLS", "").split(",")
        if u.strip()
    }
    if url in extra:
        return True
    return (urlparse(url).hostname or "") in _NONPROD_HOSTS


@pytest.fixture(autouse=True)
def _use_real_home(monkeypatch):
    """Undo the global autouse pin of $UPSCALER_HOME.

    The root conftest pins $UPSCALER_HOME to a throwaway tmp dir so unit tests
    never touch a developer's real ~/.upscaler. Integration tests are the
    deliberate exception: they must read the real token written by
    `upscaler --profile dev login`, so we drop the override and fall back to
    ~/.upscaler.
    """
    monkeypatch.delenv("UPSCALER_HOME", raising=False)


@pytest.fixture
def profile():
    """The profile under test (default `dev`, which maps to staging)."""
    return os.environ.get("UPSCALER_INTEGRATION_PROFILE", "dev")


@pytest.fixture
def server_url(profile):
    """Resolve the profile's server URL; skip if it is not an allowed host."""
    url = CLIConfig(profile=profile).resolve_server_url(None)
    if not _is_allowed_server(url):
        pytest.skip(
            f"Profile {profile!r} resolves to {url!r}, not a known non-prod host "
            f"({sorted(_NONPROD_HOSTS)}). Set UPSCALER_INTEGRATION_ALLOW_URLS to "
            f"opt in, or use a profile that targets staging/local."
        )
    return url


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def require_auth(runner, profile, server_url):
    """Skip the test unless `profile` has a live, non-expired session.

    Reuses the CLI's own `status` command (json mode) as the readiness probe so
    the precondition matches exactly how the rest of the CLI authenticates.
    """
    result = runner.invoke(cli, ["--json", "--profile", profile, "status"])
    try:
        data = json.loads(result.output)
    except (json.JSONDecodeError, ValueError):
        pytest.skip(f"Could not read auth status for profile {profile!r}: {result.output!r}")
    if not data.get("authenticated"):
        pytest.skip(
            f"Profile {profile!r} is not authenticated. "
            f"Run: upscaler --profile {profile} login"
        )
    if data.get("expired"):
        pytest.skip(
            f"Profile {profile!r} token is expired. "
            f"Run: upscaler --profile {profile} refresh (or login)"
        )
    return data


def list_items(data):
    """Normalize a /list `data` payload to a list of items.

    The endpoint returns either a bare list or a paginated dict
    ({"items": [...], "total": N}); callers shouldn't care which.
    """
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def invoke(runner, profile, *args, json_mode=True):
    """Invoke the CLI for `profile`, returning the Click result.

    Centralizes the `--json --profile <p>` prefix so test bodies read as the
    command they represent.
    """
    base = ["--json", "--profile", profile] if json_mode else ["--profile", profile]
    return runner.invoke(cli, base + list(args))
