"""Shared test fixtures for up-sdk tests."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_cli_env(monkeypatch, tmp_path):
    """Strip env vars that flip CLI defaults and pin $UPSCALER_HOME to tmp.

    Why: UPSCALER_OUTPUT=json in a developer's shell flips the CLI's default
    output mode to JSON, breaking tests that assert on human-readable output
    without passing --json explicitly. UPSCALER_HOME is pinned so tests never
    touch the developer's real ~/.upscaler dir when profile-aware defaults
    kick in (CLIConfig()/TokenStore() with no args).
    """
    for var in (
        "UPSCALER_OUTPUT",
        "UPSCALER_SERVER",
        "UPSCALER_VERIFY_SSL",
        "UPSCALER_PROFILE",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / ".upscaler-test-home"))


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Temporary directory simulating ~/.upscaler/."""
    config_dir = tmp_path / ".upscaler"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def sample_token_data():
    """Sample TokenData dict for testing."""
    return {
        "access_token": "test_access_token_abc123",
        "refresh_token": "test_refresh_token_xyz789",
        "expires_at": 9999999999.0,
        "client_id": "client_123",
        "client_secret": "secret_456",
        "organization_id": "org_789",
        "token_endpoint": "https://api.example.com/oauth/token",
    }


@pytest.fixture
def expired_token_data(sample_token_data):
    """Sample TokenData with expired access token."""
    return {**sample_token_data, "expires_at": 0.0}
