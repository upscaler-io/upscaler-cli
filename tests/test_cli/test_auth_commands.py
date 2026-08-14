"""Tests for auth CLI commands."""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.auth import _is_headless
from upscaler_cli.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def valid_token():
    from upscaler_cli.auth.token_store import TokenData

    return TokenData(
        access_token="tok",
        refresh_token="ref",
        expires_at=time.time() + 3600,
        client_id="c",
        client_secret="s",
        organization_id="org_1",
        token_endpoint="https://example.com/token",
    )


@pytest.fixture
def expired_token():
    from upscaler_cli.auth.token_store import TokenData

    return TokenData(
        access_token="tok",
        refresh_token="ref",
        expires_at=0.0,
        client_id="c",
        client_secret="s",
        organization_id=None,
        token_endpoint="https://example.com/token",
    )


class TestStatus:
    def test_status_not_authenticated(self, runner):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.side_effect = RuntimeError("Not logged in")
            result = runner.invoke(cli, ["status"])
            assert "Not authenticated" in result.output

    def test_status_authenticated(self, runner, valid_token):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.return_value = valid_token
            result = runner.invoke(cli, ["status"])
            assert "Authenticated" in result.output
            assert "org_1" in result.output
            assert "Expires in:" in result.output
            assert "Refresh token: present" in result.output

    def test_status_missing_refresh_token(self, runner, valid_token):
        from dataclasses import replace

        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.return_value = replace(valid_token, refresh_token="")
            result = runner.invoke(cli, ["status"])
            assert "Refresh token: missing" in result.output

    def test_status_expired(self, runner, expired_token):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.return_value = expired_token
            result = runner.invoke(cli, ["status"])
            assert "Authenticated" in result.output
            assert "expired" in result.output

    def test_status_json_not_authenticated(self, runner):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.side_effect = RuntimeError("Not logged in")
            result = runner.invoke(cli, ["--json", "status"])
            data = json.loads(result.output)
            assert data["authenticated"] is False

    def test_status_json_authenticated(self, runner, valid_token):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.return_value = valid_token
            result = runner.invoke(cli, ["--json", "status"])
            data = json.loads(result.output)
            assert data["authenticated"] is True
            assert data["expired"] is False
            assert data["organization_id"] == "org_1"
            assert "expires_in" in data
            assert data["refresh_token_present"] is True

    def test_status_json_missing_refresh_token(self, runner, valid_token):
        from dataclasses import replace

        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.return_value = replace(valid_token, refresh_token="")
            result = runner.invoke(cli, ["--json", "status"])
            data = json.loads(result.output)
            assert data["refresh_token_present"] is False

    def test_status_json_expired(self, runner, expired_token):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.return_value = expired_token
            result = runner.invoke(cli, ["--json", "status"])
            data = json.loads(result.output)
            assert data["authenticated"] is True
            assert data["expired"] is True


class TestLogout:
    def test_logout_not_logged_in(self, runner):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.side_effect = RuntimeError("Not logged in")
            result = runner.invoke(cli, ["logout"])
            assert "Not logged in" in result.output

    def test_logout_success(self, runner, valid_token):
        with (
            patch("upscaler_cli.auth.token_store.TokenStore") as MockStore,
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
        ):
            MockStore.return_value.load.return_value = valid_token
            MockConfig.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockFlow.return_value.revoke = AsyncMock()
            result = runner.invoke(cli, ["logout"])
            assert "Logged out" in result.output
            MockStore.return_value.delete.assert_called_once()

    def test_logout_json_not_logged_in(self, runner):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.side_effect = RuntimeError("Not logged in")
            result = runner.invoke(cli, ["--json", "logout"])
            data = json.loads(result.output)
            assert data["success"] is True
            assert "Not logged in" in data["message"]

    def test_logout_json_success(self, runner, valid_token):
        with (
            patch("upscaler_cli.auth.token_store.TokenStore") as MockStore,
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
        ):
            MockStore.return_value.load.return_value = valid_token
            MockConfig.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockFlow.return_value.revoke = AsyncMock()
            result = runner.invoke(cli, ["--json", "logout"])
            data = json.loads(result.output)
            assert data["success"] is True


class TestRefresh:
    def test_refresh_not_logged_in(self, runner):
        with patch("upscaler_cli.auth.token_store.TokenStore") as MockStore:
            MockStore.return_value.load.side_effect = RuntimeError("Not logged in")
            result = runner.invoke(cli, ["refresh"])
            assert result.exit_code != 0

    def test_refresh_success(self, runner, valid_token):
        from upscaler_cli.auth.token_store import TokenData

        new_token = TokenData(
            access_token="new_tok",
            refresh_token="new_ref",
            expires_at=time.time() + 7200,
            client_id="c",
            client_secret="s",
            organization_id="org_1",
            token_endpoint="https://example.com/token",
        )
        with (
            patch("upscaler_cli.auth.token_store.TokenStore") as MockStore,
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
        ):
            MockStore.return_value.load.return_value = valid_token
            MockConfig.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockFlow.return_value.refresh = AsyncMock(return_value=new_token)
            result = runner.invoke(cli, ["refresh"])
            assert result.exit_code == 0
            assert "refreshed" in result.output.lower()
            MockStore.return_value.save.assert_called_once_with(new_token)


class TestIsHeadless:
    def test_ci_env_is_headless(self):
        with patch.dict("os.environ", {"CI": "true"}, clear=False):
            assert _is_headless() is True

    def test_ssh_without_display_is_headless(self):
        env = {"SSH_CONNECTION": "1.2.3.4 1234 5.6.7.8 22"}
        with patch.dict("os.environ", env, clear=False):
            # Remove DISPLAY if present
            with patch.dict("os.environ", {}, clear=False):
                import os
                os.environ.pop("DISPLAY", None)
                assert _is_headless() is True

    def test_docker_container_is_headless(self):
        with patch("os.path.exists", side_effect=lambda p: p == "/.dockerenv"):
            assert _is_headless() is True

    def test_container_env_is_headless(self):
        with patch.dict("os.environ", {"container": "podman"}, clear=False):
            assert _is_headless() is True

    def test_normal_desktop_is_not_headless(self):
        """macOS/desktop with 'open' available is not headless."""
        env_clean = {
            k: v for k, v in __import__("os").environ.items()
            if k not in ("CI", "SSH_CONNECTION", "container")
        }
        with patch.dict("os.environ", env_clean, clear=True):
            with patch("os.path.exists", return_value=False):
                with patch("sys.platform", "darwin"):
                    with patch("shutil.which", side_effect=lambda cmd: (
                        "/usr/bin/open" if cmd == "open" else None
                    )):
                        assert _is_headless() is False


class TestLoginDeviceFlow:
    """Tests for the two-step device authorization flow."""

    @pytest.fixture
    def pending_data(self):
        return {
            "device_code": "dev_code_123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://app.example.com/auth/device",
            "expires_at": time.time() + 600,
            "server_url": "https://api.example.com",
        }

    def test_no_browser_requests_device_code(self, runner):
        """--no-browser requests a device code and saves pending file."""
        pending = {
            "device_code": "dev_code_123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://app.example.com/auth/device",
            "expires_at": time.time() + 600,
            "server_url": "https://api.example.com",
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
            patch("upscaler_cli.cli.auth._save_pending_device") as mock_save,
        ):
            MockConfig.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockConfig.return_value.resolve_verify_ssl.return_value = True
            MockFlow.return_value.request_device_code = AsyncMock(return_value=pending)

            result = runner.invoke(cli, ["login", "--no-browser"])

            assert result.exit_code == 0
            mock_save.assert_called_once_with(pending, "prod")

    def test_no_browser_json_output(self, runner):
        """--no-browser --json returns structured device code data."""
        pending = {
            "device_code": "dev_code_123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://app.example.com/auth/device",
            "expires_at": time.time() + 600,
            "server_url": "https://api.example.com",
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
            patch("upscaler_cli.cli.auth._save_pending_device"),
        ):
            MockConfig.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockConfig.return_value.resolve_verify_ssl.return_value = True
            MockFlow.return_value.request_device_code = AsyncMock(return_value=pending)

            result = runner.invoke(cli, ["--json", "login", "--no-browser"])

            data = json.loads(result.output)
            assert data["success"] is True
            assert data["action"] == "device_code_requested"
            assert data["data"]["user_code"] == "ABCD-1234"
            assert data["data"]["verification_uri"] == "https://app.example.com/auth/device"
            assert "next_step" in data["data"]

    def test_check_success(self, runner, valid_token, pending_data):
        """--check exchanges pending device code for tokens."""
        with (
            patch("upscaler_cli.auth.token_store.TokenStore") as MockStore,
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
            patch("upscaler_cli.cli.auth._load_pending_device", return_value=pending_data),
            patch("upscaler_cli.cli.auth._delete_pending_device") as mock_delete,
        ):
            MockConfig.return_value.resolve_verify_ssl.return_value = True
            MockFlow.return_value.check_device_code = AsyncMock(return_value=valid_token)

            result = runner.invoke(cli, ["login", "--check"])

            assert result.exit_code == 0
            MockStore.return_value.save.assert_called_once_with(valid_token)
            mock_delete.assert_called_once()

    def test_check_pending(self, runner, pending_data):
        """--check returns pending status when user hasn't authorized yet."""
        from upscaler_cli.auth.oauth import DevicePendingError

        with (
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
            patch("upscaler_cli.cli.auth._load_pending_device", return_value=pending_data),
        ):
            MockConfig.return_value.resolve_verify_ssl.return_value = True
            MockFlow.return_value.check_device_code = AsyncMock(
                side_effect=DevicePendingError("pending")
            )

            result = runner.invoke(cli, ["login", "--check"])

            assert result.exit_code == 1

    def test_check_pending_json(self, runner, pending_data):
        """--check --json returns structured pending status."""
        from upscaler_cli.auth.oauth import DevicePendingError

        with (
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
            patch("upscaler_cli.cli.auth._load_pending_device", return_value=pending_data),
        ):
            MockConfig.return_value.resolve_verify_ssl.return_value = True
            MockFlow.return_value.check_device_code = AsyncMock(
                side_effect=DevicePendingError("pending")
            )

            result = runner.invoke(cli, ["--json", "login", "--check"])

            data = json.loads(result.output)
            assert data["pending"] is True
            assert "expires_in" in data

    def test_check_no_pending_file(self, runner):
        """--check with no pending file exits with error."""
        with patch("upscaler_cli.cli.auth._load_pending_device", return_value=None):
            result = runner.invoke(cli, ["login", "--check"])
            assert result.exit_code == 2

    def test_check_expired(self, runner):
        """--check with expired device code exits with error."""
        expired_pending = {
            "device_code": "dev_code_123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://app.example.com/auth/device",
            "expires_at": 0.0,  # already expired
            "server_url": "https://api.example.com",
        }
        with (
            patch("upscaler_cli.cli.auth._load_pending_device", return_value=expired_pending),
            patch("upscaler_cli.cli.auth._delete_pending_device") as mock_delete,
        ):
            result = runner.invoke(cli, ["login", "--check"])
            assert result.exit_code == 2
            mock_delete.assert_called_once()

    def test_headless_auto_detect_uses_device_flow(self, runner):
        """When headless is detected, login uses device flow without --no-browser."""
        pending = {
            "device_code": "dev_code_123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://app.example.com/auth/device",
            "expires_at": time.time() + 600,
            "server_url": "https://api.example.com",
        }
        with (
            patch("upscaler_cli.config.CLIConfig") as MockConfig,
            patch("upscaler_cli.auth.oauth.OAuthFlow") as MockFlow,
            patch("upscaler_cli.cli.auth._is_headless", return_value=True),
            patch("upscaler_cli.cli.auth._save_pending_device"),
        ):
            MockConfig.return_value.resolve_server_url.return_value = "https://api.example.com"
            MockConfig.return_value.resolve_verify_ssl.return_value = True
            MockFlow.return_value.request_device_code = AsyncMock(return_value=pending)
            MockFlow.return_value.login = AsyncMock()

            result = runner.invoke(cli, ["login"])

            # Should have called request_device_code, not login
            MockFlow.return_value.request_device_code.assert_called_once()
            MockFlow.return_value.login.assert_not_called()
            assert result.exit_code == 0
