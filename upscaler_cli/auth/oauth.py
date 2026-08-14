"""OAuth2 Authorization Code + PKCE flow for CLI login.

Flow:
1. Register client via Dynamic Client Registration (DCR)
2. Generate PKCE code verifier + challenge
3. Start localhost HTTP server for callback
4. Open browser to authorize URL
5. Wait for callback with auth code
6. Exchange code for tokens
7. Return TokenData

Also supports:
- Token refresh (refresh_token grant)
- Token revocation (best-effort)
"""

import asyncio
import base64
import hashlib
import html
import http.server
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from typing import Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from upscaler_cli.auth.token_store import TokenData

logger = logging.getLogger(__name__)


class DevicePendingError(Exception):
    """Raised when a device code check finds authorization still pending."""

    pass


# Default callback port for localhost server
DEFAULT_PORT = 19876
LOGIN_TIMEOUT = 120  # seconds


# Device flow polling config
DEVICE_POLL_INTERVAL = 5  # seconds between polls
DEVICE_CODE_TIMEOUT = 600  # 10 minutes


def _detect_env(server_url: str) -> str:
    """Return a short env tag derived from the server URL.

    Returns:
        "dev" for localhost / 127.0.0.1
        "stag" for *.stg.* hosts
        "" for production (or anything unrecognized) — no suffix shown
    """
    url = (server_url or "").lower()
    if "localhost" in url or "127.0.0.1" in url:
        return "dev"
    if ".stg." in url or ".staging." in url:
        return "stag"
    return ""


def _build_cli_client_name(server_url: str) -> str:
    """Build the OAuth DCR client_name shown to the user on the consent screen."""
    env = _detect_env(server_url)
    return f"Upscaler CLI ({env})" if env else "Upscaler CLI"


# Inline SVGs for branded callback pages (no external requests).
_UPSCALER_LOGO_SVG = """<svg class="logo" viewBox="0 0 1001 694" fill="none"
  xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path
    d="M1000.41 231.569V462.469L800.398 577.936L600.4 693.405L0.412109 347.003
       L200.426 231.524L800.398 577.936V347.037L400.358 116.074L600.372 0.595459
       L1000.41 231.569Z"
    fill="url(#upscalerLogoGradient)"/>
  <defs>
    <linearGradient id="upscalerLogoGradient" x1="0" y1="347" x2="605" y2="0"
      gradientUnits="userSpaceOnUse">
      <stop stop-color="#5E6CFE"/>
      <stop offset="1" stop-color="#F598E9"/>
    </linearGradient>
  </defs>
</svg>"""

_ICON_SUCCESS = """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true">
  <polyline points="20 6 9 17 4 12"/>
</svg>"""

_ICON_ERROR = """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true">
  <line x1="18" y1="6" x2="6" y2="18"/>
  <line x1="6" y1="6" x2="18" y2="18"/>
</svg>"""


def _render_status_page(
    variant: str,
    title: str,
    message: str,
    detail: str = "",
    auto_close: bool = False,
) -> str:
    """Render a branded HTML status page for the OAuth callback.

    Args:
        variant: "success" or "error" — controls icon color.
        title: Main heading.
        message: Body copy.
        detail: Optional secondary line (e.g. an error code from the IdP).
        auto_close: When True, attempts to close the tab after a brief delay.
    """
    icon_svg = _ICON_SUCCESS if variant == "success" else _ICON_ERROR
    icon_color = "#16a34a" if variant == "success" else "#dc2626"
    icon_bg = "#dcfce7" if variant == "success" else "#fee2e2"

    detail_html = (
        f'<p class="detail">{html.escape(detail)}</p>' if detail else ""
    )
    auto_close_script = (
        '<script>setTimeout(function(){try{window.close();}catch(e){}},2500);</script>'
        if auto_close
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upscaler — {html.escape(title)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    background: linear-gradient(135deg, #f6f7fb 0%, #fdf2fb 100%);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    color: #1f1f23;
    -webkit-font-smoothing: antialiased;
  }}
  .card {{
    background: #ffffff;
    border-radius: 16px;
    box-shadow: 0 12px 48px rgba(94, 108, 254, 0.12), 0 2px 6px rgba(0,0,0,0.04);
    padding: 48px 40px 40px;
    max-width: 440px;
    width: 100%;
    text-align: center;
  }}
  .logo {{ width: 48px; height: auto; display: block; margin: 0 auto 28px; }}
  .icon {{
    width: 72px;
    height: 72px;
    margin: 0 auto 20px;
    border-radius: 50%;
    background: {icon_bg};
    color: {icon_color};
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .icon svg {{ width: 36px; height: 36px; }}
  h1 {{
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.01em;
    margin-bottom: 10px;
  }}
  p {{
    font-size: 15px;
    line-height: 1.55;
    color: #56565e;
  }}
  .detail {{
    font-size: 13px;
    color: #8a8a92;
    margin-top: 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    word-break: break-word;
  }}
  .footer {{
    margin-top: 28px;
    font-size: 12px;
    color: #a0a0a8;
    letter-spacing: 0.02em;
  }}
</style>
</head>
<body>
  <div class="card" role="status">
    {_UPSCALER_LOGO_SVG}
    <div class="icon">{icon_svg}</div>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(message)}</p>
    {detail_html}
    <div class="footer">Upscaler CLI</div>
  </div>
  {auto_close_script}
</body>
</html>"""


def generate_pkce() -> Tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        Tuple of (verifier, challenge) where:
        - verifier: 43-128 character random string
        - challenge: base64url(sha256(verifier))
    """
    # Generate 32 random bytes → 43 character base64url string
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")

    # S256 challenge
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return verifier, challenge


def generate_state() -> str:
    """Generate random state parameter for CSRF prevention."""
    return secrets.token_urlsafe(32)


class OAuthFlow:
    """Manages OAuth2 flows: login, refresh, revoke."""

    def __init__(self, server_url: str, verify_ssl: bool = True):
        """Initialize OAuth flow.

        Args:
            server_url: Base URL of the Upscaler API (e.g., https://api.upscaler.com)
            verify_ssl: If False, skip SSL certificate verification.
        """
        self.server_url = server_url.rstrip("/")
        self.oauth_base = f"{self.server_url}/mcp"
        self.verify_ssl = verify_ssl

    async def register_client(self) -> Tuple[str, str]:
        """Register a new OAuth client via Dynamic Client Registration.

        Returns:
            Tuple of (client_id, client_secret).
        """
        # client_name shown on the consent screen — tagged with the env so a
        # user can tell a dev/stag authorization apart from production at a
        # glance. Production gets no suffix.
        url = f"{self.oauth_base}/register"
        payload = {
            "client_name": _build_cli_client_name(self.server_url),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "redirect_uris": [f"http://127.0.0.1:{DEFAULT_PORT}/callback"],
            "token_endpoint_auth_method": "client_secret_post",
        }

        async with httpx.AsyncClient(timeout=30.0, verify=self.verify_ssl) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        return data["client_id"], data["client_secret"]

    async def login(self, port: int = DEFAULT_PORT) -> TokenData:
        """Run full OAuth2 PKCE login flow.

        Args:
            port: Localhost port for callback server.

        Returns:
            TokenData with access + refresh tokens.

        Raises:
            RuntimeError: On timeout, port conflict, or auth failure.
        """
        # Check port availability
        if not self._is_port_available(port):
            raise RuntimeError(
                f"Login callback port {port} in use. Use --port to specify another."
            )

        # Register client
        client_id, client_secret = await self.register_client()

        # Generate PKCE
        verifier, challenge = generate_pkce()
        state = generate_state()

        # Start callback server
        auth_code_holder = {"code": None, "error": None}
        server = self._start_callback_server(port, state, auth_code_holder)

        try:
            # Build authorize URL
            redirect_uri = f"http://127.0.0.1:{port}/callback"
            params = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
            }
            authorize_url = f"{self.oauth_base}/authorize?{urlencode(params)}"

            # Open browser
            if not webbrowser.open(authorize_url):
                print(
                    f"Open this URL in your browser: {authorize_url}", file=sys.stderr
                )

            # Wait for callback
            deadline = time.time() + LOGIN_TIMEOUT
            while time.time() < deadline:
                if auth_code_holder["code"] or auth_code_holder["error"]:
                    break
                await asyncio.sleep(0.5)

            if auth_code_holder["error"]:
                raise RuntimeError(f"Login failed: {auth_code_holder['error']}")

            if not auth_code_holder["code"]:
                raise RuntimeError("Login timed out. Run upscaler login to try again.")

            # Exchange code for tokens
            token_data = await self._exchange_code(
                code=auth_code_holder["code"],
                verifier=verifier,
                redirect_uri=redirect_uri,
                client_id=client_id,
                client_secret=client_secret,
            )

            return token_data

        finally:
            server.shutdown()

    async def request_device_code(self) -> dict:
        """Request a device code for headless authorization (RFC 8628 step 1).

        Returns a dict with device_code, user_code, verification_uri, and
        expires_in. The caller should display the URL and code to the user,
        then persist the device_code for later use with check_device_code().

        Returns:
            Dict with keys: device_code, user_code, verification_uri,
            expires_at (absolute timestamp).

        Raises:
            RuntimeError: On server error or connectivity failure.
        """
        url = f"{self.server_url}/api/v1/device/code"
        payload = {"client_name": _build_cli_client_name(self.server_url)}

        async with httpx.AsyncClient(timeout=30.0, verify=self.verify_ssl) as client:
            response = await client.post(url, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Device authorization request failed ({response.status_code}). "
                "Check server connectivity."
            )

        data = response.json()
        expires_in = data.get("expires_in", DEVICE_CODE_TIMEOUT)

        return {
            "device_code": data["device_code"],
            "user_code": data["user_code"],
            "verification_uri": data["verification_uri"],
            "expires_at": time.time() + expires_in,
            "server_url": self.server_url,
        }

    async def check_device_code(self, device_code: str) -> TokenData:
        """Check if a device code has been authorized (RFC 8628 step 2).

        Makes a single token exchange attempt. Does not poll.

        Args:
            device_code: The device_code from request_device_code().

        Returns:
            TokenData with access + refresh tokens.

        Raises:
            DevicePendingError: User has not yet authorized.
            RuntimeError: On denial, expiry, or server error.
        """
        token_url = f"{self.server_url}/api/v1/device/token"

        async with httpx.AsyncClient(timeout=30.0, verify=self.verify_ssl) as client:
            response = await client.post(
                token_url,
                json={"device_code": device_code},
            )

        if response.status_code == 200:
            token_data = response.json()
            return TokenData(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token", ""),
                expires_at=time.time() + token_data.get("expires_in", 3600),
                client_id=token_data.get("client_id", "device"),
                client_secret=token_data.get("client_secret", ""),
                organization_id=token_data.get("organization_id"),
                token_endpoint=f"{self.oauth_base}/token",
            )

        poll_data = response.json()
        error = poll_data.get("error", "")

        if error == "authorization_pending":
            raise DevicePendingError("Authorization pending. User has not yet authorized.")
        elif error == "slow_down":
            raise DevicePendingError("Authorization pending (slow down).")
        elif error == "access_denied":
            raise RuntimeError("Authorization denied by user.")
        elif error == "expired_token":
            raise RuntimeError(
                "Device code expired. Run: upscaler login --no-browser"
            )
        else:
            raise RuntimeError(
                f"Device authorization failed: {poll_data.get('error_description', error)}"
            )

    async def refresh(self, token_data: TokenData) -> TokenData:
        """Exchange refresh token for new access + refresh tokens.

        Args:
            token_data: Current token data with refresh_token.

        Returns:
            Updated TokenData with new tokens.

        Raises:
            RuntimeError: If refresh fails (session expired).
        """
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": token_data.refresh_token,
            "client_id": token_data.client_id,
            "client_secret": token_data.client_secret,
        }

        async with httpx.AsyncClient(timeout=30.0, verify=self.verify_ssl) as client:
            response = await client.post(token_data.token_endpoint, data=payload)

        if response.status_code != 200:
            raise RuntimeError("Session expired. Run: upscaler login")

        data = response.json()
        return TokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", token_data.refresh_token),
            expires_at=time.time() + data.get("expires_in", 86400),
            client_id=token_data.client_id,
            client_secret=token_data.client_secret,
            # Read org from the refresh response (matching the login path) so a
            # refreshed session reflects the token's real scope. Fall back to the
            # existing value only when the endpoint OMITS the key; an explicit
            # empty value means the org was cleared and must win over the stale
            # one (a plain `or` would mistake "" for "omitted").
            organization_id=(
                data["organization_id"]
                if "organization_id" in data
                else token_data.organization_id
            ),
            token_endpoint=token_data.token_endpoint,
        )

    async def revoke(self, token_data: TokenData) -> None:
        """Revoke tokens (best-effort — does not raise on failure)."""
        url = f"{self.oauth_base}/revoke"
        payload = {
            "token": token_data.access_token,
            "client_id": token_data.client_id,
            "client_secret": token_data.client_secret,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0, verify=self.verify_ssl) as client:
                await client.post(url, data=payload)
        except Exception as e:
            logger.debug(f"Token revocation failed (best-effort): {e}")

    async def _exchange_code(
        self,
        code: str,
        verifier: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
    ) -> TokenData:
        """Exchange authorization code for tokens."""
        token_url = f"{self.oauth_base}/token"
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": client_id,
            "client_secret": client_secret,
        }

        async with httpx.AsyncClient(timeout=30.0, verify=self.verify_ssl) as client:
            response = await client.post(token_url, data=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Token exchange failed ({response.status_code}). Run: upscaler login"
            )

        data = response.json()
        return TokenData(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + data.get("expires_in", 86400),
            client_id=client_id,
            client_secret=client_secret,
            organization_id=data.get("organization_id"),
            token_endpoint=token_url,
        )

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available for binding."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return True
        except OSError:
            return False

    def _start_callback_server(
        self, port: int, expected_state: str, result_holder: dict
    ) -> http.server.HTTPServer:
        """Start a localhost HTTP server to receive the OAuth callback."""

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def _send_html(self, status_code: int, body_html: str) -> None:
                body = body_html.encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlparse(self.path)

                # Ignore non-callback requests (favicon, prefetch, etc.)
                if not parsed.path.rstrip("/").endswith("/callback"):
                    self.send_response(204)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)

                state = params.get("state", [None])[0]
                code = params.get("code", [None])[0]
                error = params.get("error", [None])[0]

                if error:
                    result_holder["error"] = error
                    self._send_html(
                        200,
                        _render_status_page(
                            variant="error",
                            title="Authorization Failed",
                            message="We couldn't complete the sign-in.",
                            detail=error,
                        ),
                    )
                    return

                if state != expected_state:
                    result_holder["error"] = "State mismatch — possible CSRF attack"
                    self._send_html(
                        400,
                        _render_status_page(
                            variant="error",
                            title="Sign-in Cancelled",
                            message=(
                                "The authorization request didn't match. "
                                "Please try again from your terminal."
                            ),
                        ),
                    )
                    return

                if code:
                    result_holder["code"] = code
                    self._send_html(
                        200,
                        _render_status_page(
                            variant="success",
                            title="You're all set",
                            message=(
                                "Authorization successful. You can close this "
                                "tab and return to your terminal."
                            ),
                            auto_close=True,
                        ),
                    )

            def log_message(self, format, *args):
                pass  # Suppress server logs

        server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
