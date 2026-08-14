"""Tests for upscaler_cli.client.UpscalerClient module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from upscaler_cli.auth.token_store import TokenData
from upscaler_cli.client import UpscalerClient
from upscaler_cli.errors import APIError, AuthRequiredError


def _make_token_data():
    """Create a sample TokenData for testing."""
    return TokenData(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_at=9999999999.0,
        client_id="client_123",
        client_secret="secret_456",
        organization_id="org_789",
        token_endpoint="https://api.example.com/mcp/token",
    )


def _make_mock_response(status_code=200, body=None):
    """Create a mock httpx.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.content = json.dumps(body or {}).encode()
    mock.json.return_value = body or {}
    return mock


def _make_mock_client(response):
    """Create a mock httpx.AsyncClient context manager."""
    mock_client = AsyncMock()
    mock_client.request.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _make_token_store(token_data=None, load_error=None):
    """Create a mock TokenStore."""
    store = MagicMock()
    if load_error:
        store.load.side_effect = load_error
    else:
        store.load.return_value = token_data or _make_token_data()
    return store


# ---- Bearer token ----


@pytest.mark.asyncio
async def test_request_adds_bearer_token():
    """Authorization header is set with Bearer token."""
    token_data = _make_token_data()
    store = _make_token_store(token_data)
    client = UpscalerClient("https://api.example.com", token_store=store)

    mock_response = _make_mock_response(200, {"ok": True})
    mock_http = _make_mock_client(mock_response)

    with patch("upscaler_cli.client.httpx.AsyncClient", return_value=mock_http):
        await client.request("GET", "/api/v1/search")

    call_kwargs = mock_http.request.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
    assert headers["Authorization"] == f"Bearer {token_data.access_token}"


# ---- X-Request-Id ----


@pytest.mark.asyncio
async def test_request_adds_request_id():
    """X-Request-Id header is set on every request."""
    store = _make_token_store()
    client = UpscalerClient("https://api.example.com", token_store=store)

    mock_response = _make_mock_response(200, {"ok": True})
    mock_http = _make_mock_client(mock_response)

    with patch("upscaler_cli.client.httpx.AsyncClient", return_value=mock_http):
        await client.request("GET", "/api/v1/search")

    call_kwargs = mock_http.request.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
    assert "X-Request-Id" in headers
    assert len(headers["X-Request-Id"]) > 0


@pytest.mark.asyncio
async def test_request_sends_upscaler_cli_user_agent():
    """User-Agent identifies the CLI so backend actor tracing can tag it."""
    from upscaler_cli import __version__

    store = _make_token_store()
    client = UpscalerClient("https://api.example.com", token_store=store)

    mock_response = _make_mock_response(200, {"ok": True})
    mock_http = _make_mock_client(mock_response)

    with patch("upscaler_cli.client.httpx.AsyncClient", return_value=mock_http):
        await client.request("GET", "/api/v1/search")

    call_kwargs = mock_http.request.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
    assert headers["User-Agent"] == f"UpscalerCLI/{__version__}"


# ---- 401 triggers refresh ----


@pytest.mark.asyncio
async def test_401_triggers_refresh():
    """On 401, client refreshes token and retries the request."""
    token_data = _make_token_data()
    store = _make_token_store(token_data)
    client = UpscalerClient("https://api.example.com", token_store=store)

    response_401 = _make_mock_response(401, {"error": "unauthorized"})
    response_200 = _make_mock_response(200, {"ok": True})

    mock_http = AsyncMock()
    mock_http.request.side_effect = [response_401, response_200]
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    new_token_data = _make_token_data()
    new_token_data.access_token = "refreshed_token"

    with (
        patch("upscaler_cli.client.httpx.AsyncClient", return_value=mock_http),
        patch.object(
            client, "_refresh_token",
            new_callable=AsyncMock,
            return_value=new_token_data,
        ) as mock_refresh,
    ):
        result = await client.request("GET", "/api/v1/search")
        assert result == {"ok": True}
        mock_refresh.assert_awaited_once_with(token_data)


# ---- 401 refresh fails ----


@pytest.mark.asyncio
async def test_401_refresh_fails_raises_auth_error():
    """When 401 and refresh also fails, AuthRequiredError is raised."""
    token_data = _make_token_data()
    store = _make_token_store(token_data)
    client = UpscalerClient("https://api.example.com", token_store=store)

    response_401 = _make_mock_response(401, {"error": "unauthorized"})

    mock_http = _make_mock_client(response_401)

    with (
        patch("upscaler_cli.client.httpx.AsyncClient", return_value=mock_http),
        patch.object(
            client,
            "_refresh_token",
            new_callable=AsyncMock,
            side_effect=RuntimeError("refresh failed"),
        ),
    ):
        with pytest.raises(AuthRequiredError, match="Session expired"):
            await client.request("GET", "/api/v1/search")


# ---- not logged in ----


@pytest.mark.asyncio
async def test_not_logged_in_raises_auth_error():
    """When token_store.load() raises RuntimeError, AuthRequiredError is raised."""
    store = _make_token_store(load_error=RuntimeError("Not logged in"))
    client = UpscalerClient("https://api.example.com", token_store=store)

    with pytest.raises(AuthRequiredError, match="Not logged in"):
        await client.request("GET", "/api/v1/search")


# ---- API error ----


@pytest.mark.asyncio
async def test_api_error_raised():
    """400 response raises APIError with the error message."""
    store = _make_token_store()
    client = UpscalerClient("https://api.example.com", token_store=store)

    mock_response = _make_mock_response(400, {"error": "Bad request: missing field"})
    mock_http = _make_mock_client(mock_response)

    with patch("upscaler_cli.client.httpx.AsyncClient", return_value=mock_http):
        with pytest.raises(APIError, match="Bad request: missing field"):
            await client.request("POST", "/api/v1/records")
