"""Tests for upscaler_cli.auth.oauth module."""

import base64
import hashlib
import socket
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from upscaler_cli.auth.oauth import DevicePendingError, OAuthFlow, generate_pkce, generate_state
from upscaler_cli.auth.token_store import TokenData

# ---- generate_pkce ----


def test_pkce_verifier_length():
    """Verifier is 43 chars (32 bytes base64url without padding)."""
    verifier, _ = generate_pkce()
    assert len(verifier) == 43


def test_pkce_challenge_is_sha256():
    """Challenge equals base64url(sha256(verifier)) without padding."""
    verifier, challenge = generate_pkce()

    expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")

    assert challenge == expected_challenge


# ---- generate_state ----


def test_generate_state_unique():
    """Two calls to generate_state produce different values."""
    state1 = generate_state()
    state2 = generate_state()
    assert state1 != state2


# ---- OAuthFlow.refresh ----


@pytest.mark.asyncio
async def test_refresh_success():
    """Successful refresh returns new TokenData with updated tokens."""
    flow = OAuthFlow("https://api.example.com")
    token_data = TokenData(
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=0.0,
        client_id="client_123",
        client_secret="secret_456",
        organization_id="org_789",
        token_endpoint="https://api.example.com/mcp/token",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_in": 3600,
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await flow.refresh(token_data)

    assert result.access_token == "new_access"
    assert result.refresh_token == "new_refresh"
    assert result.client_id == "client_123"
    assert result.client_secret == "secret_456"
    # Response omits organization_id: fall back to the existing value.
    assert result.organization_id == "org_789"


@pytest.mark.asyncio
async def test_refresh_updates_org_from_response():
    """When the refresh response carries an org, it overrides the stale value."""
    flow = OAuthFlow("https://api.example.com")
    token_data = TokenData(
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=0.0,
        client_id="client_123",
        client_secret="secret_456",
        organization_id="org_stale",
        token_endpoint="https://api.example.com/mcp/token",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_in": 3600,
        "organization_id": "org_fresh",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await flow.refresh(token_data)

    assert result.organization_id == "org_fresh"


@pytest.mark.asyncio
async def test_refresh_empty_org_clears_stale_value():
    """An explicit empty organization_id in the refresh response clears the
    stale org (present-but-empty wins over the fallback), matching the login
    path which reads the response value directly."""
    flow = OAuthFlow("https://api.example.com")
    token_data = TokenData(
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=0.0,
        client_id="client_123",
        client_secret="secret_456",
        organization_id="org_stale",
        token_endpoint="https://api.example.com/mcp/token",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_in": 3600,
        "organization_id": "",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await flow.refresh(token_data)

    assert result.organization_id == ""


@pytest.mark.asyncio
async def test_refresh_expired():
    """Non-200 response from refresh raises RuntimeError."""
    flow = OAuthFlow("https://api.example.com")
    token_data = TokenData(
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=0.0,
        client_id="client_123",
        client_secret="secret_456",
        organization_id="org_789",
        token_endpoint="https://api.example.com/mcp/token",
    )

    mock_response = MagicMock()
    mock_response.status_code = 401

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Session expired"):
            await flow.refresh(token_data)


# ---- OAuthFlow.revoke ----


@pytest.mark.asyncio
async def test_revoke_best_effort():
    """Revoke swallows exceptions and does not raise."""
    flow = OAuthFlow("https://api.example.com")
    token_data = TokenData(
        access_token="access_tok",
        refresh_token="refresh_tok",
        expires_at=9999999999.0,
        client_id="client_123",
        client_secret="secret_456",
        organization_id="org_789",
        token_endpoint="https://api.example.com/mcp/token",
    )

    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("network error")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        # Should not raise
        await flow.revoke(token_data)


# ---- _is_port_available ----


def test_port_check_available():
    """_is_port_available returns True for an unused port."""
    flow = OAuthFlow("https://api.example.com")
    # Use a high ephemeral port unlikely to be in use
    assert flow._is_port_available(49123) is True


def test_port_check_unavailable():
    """_is_port_available returns False when the port is already bound."""
    flow = OAuthFlow("https://api.example.com")

    # Bind a port so it becomes unavailable
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        bound_port = s.getsockname()[1]

        assert flow._is_port_available(bound_port) is False


# ---- request_device_code ----


@pytest.mark.asyncio
async def test_request_device_code_success():
    """request_device_code returns pending data with device_code and user_code."""
    flow = OAuthFlow("https://api.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "device_code": "dev_abc",
        "user_code": "WXYZ-5678",
        "verification_uri": "https://app.example.com/auth/device",
        "expires_in": 600,
        "interval": 5,
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await flow.request_device_code()

    assert result["device_code"] == "dev_abc"
    assert result["user_code"] == "WXYZ-5678"
    assert result["verification_uri"] == "https://app.example.com/auth/device"
    assert result["server_url"] == "https://api.example.com"
    assert result["expires_at"] > time.time()


@pytest.mark.asyncio
async def test_request_device_code_server_error():
    """request_device_code raises RuntimeError on non-200."""
    flow = OAuthFlow("https://api.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 500

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Device authorization request failed"):
            await flow.request_device_code()


# ---- check_device_code ----


@pytest.mark.asyncio
async def test_check_device_code_success():
    """check_device_code returns TokenData when authorized."""
    flow = OAuthFlow("https://api.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "access_abc",
        "refresh_token": "refresh_xyz",
        "expires_in": 3600,
        "client_id": "device",
        "organization_id": "org_1",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        result = await flow.check_device_code("dev_abc")

    assert result.access_token == "access_abc"
    assert result.refresh_token == "refresh_xyz"
    assert result.client_id == "device"
    assert result.organization_id == "org_1"


@pytest.mark.asyncio
async def test_check_device_code_pending():
    """check_device_code raises DevicePendingError when not yet authorized."""
    flow = OAuthFlow("https://api.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": "authorization_pending"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(DevicePendingError):
            await flow.check_device_code("dev_abc")


@pytest.mark.asyncio
async def test_check_device_code_denied():
    """check_device_code raises RuntimeError when user denies."""
    flow = OAuthFlow("https://api.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": "access_denied"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="denied"):
            await flow.check_device_code("dev_abc")


@pytest.mark.asyncio
async def test_check_device_code_expired():
    """check_device_code raises RuntimeError when device code expired."""
    flow = OAuthFlow("https://api.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": "expired_token"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("upscaler_cli.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="expired"):
            await flow.check_device_code("dev_abc")
