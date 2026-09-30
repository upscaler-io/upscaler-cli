"""Authentication CLI commands: login, refresh, status, logout."""

import asyncio
import json
import sys
import time

import click

from upscaler_cli.cli.context import pass_context


def _format_duration(seconds):
    """Format seconds into a human-readable duration."""
    if seconds >= 86400:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"
    if seconds >= 3600:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if seconds >= 60:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds}s"


def _is_headless() -> bool:
    """Detect headless environments where a browser cannot be opened.

    Returns True in containers, CI, SSH sessions, and other environments
    without display access (e.g., Claude.ai desktop app sandbox).
    """
    import os
    import shutil

    # CI environments
    if os.environ.get("CI"):
        return True

    # SSH session without X forwarding
    if os.environ.get("SSH_CONNECTION") and not os.environ.get("DISPLAY"):
        return True

    # Container indicators
    if os.path.exists("/.dockerenv") or os.environ.get("container"):
        return True

    # No DISPLAY on Linux (non-macOS, non-Windows)
    if (sys.platform.startswith("linux")
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")):
        return True

    # No browser binary available
    if (not shutil.which("xdg-open")
            and not shutil.which("open")
            and not shutil.which("sensible-browser")):
        # Last resort: try webbrowser module detection
        import webbrowser
        try:
            webbrowser.get()
        except webbrowser.Error:
            return True

    return False


@click.command()
@click.option("--port", default=19876, help="Localhost port for OAuth callback.")
@click.option(
    "--no-browser", is_flag=True, default=False,
    help="Device flow: returns a code + URL for headless authorization.",
)
@click.option(
    "--check", is_flag=True, default=False,
    help="Check if a pending device authorization has completed.",
)
@pass_context
def login(ctx, port, no_browser, check):
    """Authenticate with Upscaler via OAuth2.

    By default, opens your browser to the Upscaler login page. After
    authenticating, tokens are encrypted and stored locally.

    For environments without a browser (CI, Claude.ai, SSH), use the
    two-step device authorization flow:

    \b
    Step 1: Request a device code (returns URL + code, then exits):
        upscaler login --no-browser

    \b
    Step 2: After authorizing in your browser, check the result:
        upscaler login --check

    Examples:
        upscaler login
        upscaler login --no-browser
        upscaler login --check
        upscaler login --port 9999
        upscaler --server https://custom.upscaler.com login
    """
    if check:
        _login_check(ctx)
    elif no_browser or _is_headless():
        _login_device(ctx)
    else:
        _login_browser(ctx, port)


def _login_browser(ctx, port):
    """Browser-based OAuth2 PKCE login flow."""
    from upscaler_cli.auth.oauth import OAuthFlow
    from upscaler_cli.auth.token_store import TokenStore
    from upscaler_cli.config import CLIConfig

    config = CLIConfig(profile=ctx.profile)
    server_url = config.resolve_server_url(ctx.server_url)
    if not server_url:
        click.echo(
            "Server URL required. Use --server or: upscaler config set server_url <url>",
            err=True,
        )
        sys.exit(1)

    verify_ssl = config.resolve_verify_ssl()
    flow = OAuthFlow(server_url, verify_ssl=verify_ssl)
    store = TokenStore(profile=ctx.profile)

    try:
        if not ctx.json_mode:
            click.echo("Starting OAuth login...", err=True)
        token_data = asyncio.run(flow.login(port=port))
        store.save(token_data)

        if ctx.json_mode:
            expires_in = int(token_data.expires_at - time.time())
            click.echo(json.dumps({"success": True, "data": {"expires_in": expires_in}}))
        else:
            click.echo("Logged in successfully.", err=True)

    except RuntimeError as e:
        if ctx.json_mode:
            click.echo(json.dumps({"error": str(e)}), err=True)
        else:
            click.echo(str(e), err=True)
        sys.exit(1)


def _login_device(ctx):
    """Device flow step 1: request code, save pending, exit."""
    from upscaler_cli.auth.oauth import OAuthFlow
    from upscaler_cli.config import CLIConfig

    config = CLIConfig(profile=ctx.profile)
    server_url = config.resolve_server_url(ctx.server_url)
    if not server_url:
        click.echo(
            "Server URL required. Use --server or: upscaler config set server_url <url>",
            err=True,
        )
        sys.exit(1)

    verify_ssl = config.resolve_verify_ssl()
    flow = OAuthFlow(server_url, verify_ssl=verify_ssl)

    try:
        pending = asyncio.run(flow.request_device_code())
    except RuntimeError as e:
        if ctx.json_mode:
            click.echo(json.dumps({"error": str(e)}), err=True)
        else:
            click.echo(str(e), err=True)
        sys.exit(1)

    # Save pending device code for --check
    _save_pending_device(pending, ctx.profile)

    if ctx.json_mode:
        click.echo(json.dumps({
            "success": True,
            "action": "device_code_requested",
            "data": {
                "verification_uri": pending["verification_uri"],
                "user_code": pending["user_code"],
                "expires_at": pending["expires_at"],
                "next_step": "upscaler login --check",
            },
        }))
    else:
        click.echo(
            f"\nTo sign in, open this URL in your browser:\n\n"
            f"  {pending['verification_uri']}\n\n"
            f"Then enter this code: {pending['user_code']}\n\n"
            f"After authorizing, run: upscaler login --check",
            err=True,
        )


def _login_check(ctx):
    """Device flow step 2: check if pending authorization completed."""
    from upscaler_cli.auth.oauth import DevicePendingError, OAuthFlow
    from upscaler_cli.auth.token_store import TokenStore
    from upscaler_cli.config import CLIConfig

    pending = _load_pending_device(ctx.profile)
    if not pending:
        msg = "No pending device authorization. Run: upscaler login --no-browser"
        if ctx.json_mode:
            click.echo(json.dumps({"error": msg}), err=True)
        else:
            click.echo(msg, err=True)
        sys.exit(2)

    # Check expiry
    if time.time() >= pending["expires_at"]:
        _delete_pending_device(ctx.profile)
        msg = "Device code expired. Run: upscaler login --no-browser"
        if ctx.json_mode:
            click.echo(json.dumps({"error": msg, "expired": True}), err=True)
        else:
            click.echo(msg, err=True)
        sys.exit(2)

    config = CLIConfig(profile=ctx.profile)
    server_url = pending.get("server_url") or config.resolve_server_url(ctx.server_url)
    verify_ssl = config.resolve_verify_ssl()
    flow = OAuthFlow(server_url, verify_ssl=verify_ssl)

    try:
        token_data = asyncio.run(flow.check_device_code(pending["device_code"]))
    except DevicePendingError:
        remaining = int(pending["expires_at"] - time.time())
        if ctx.json_mode:
            click.echo(json.dumps({
                "pending": True,
                "expires_in": remaining,
                "message": "Authorization pending. User has not yet authorized.",
            }))
        else:
            click.echo(
                f"Authorization pending. Expires in {_format_duration(remaining)}.\n"
                f"After authorizing in your browser, run: upscaler login --check",
                err=True,
            )
        sys.exit(1)
    except RuntimeError as e:
        _delete_pending_device(ctx.profile)
        if ctx.json_mode:
            click.echo(json.dumps({"error": str(e)}), err=True)
        else:
            click.echo(str(e), err=True)
        sys.exit(2)

    # Success — save tokens and clean up pending file
    store = TokenStore(profile=ctx.profile)
    store.save(token_data)
    _delete_pending_device(ctx.profile)

    if ctx.json_mode:
        expires_in = int(token_data.expires_at - time.time())
        click.echo(json.dumps({"success": True, "data": {"expires_in": expires_in}}))
    else:
        click.echo("Logged in successfully.", err=True)


# ---------------------------------------------------------------------------
# Pending device code persistence (~/.upscaler/profiles/{profile}/pending_device.json)
# ---------------------------------------------------------------------------

_PENDING_FILE = "pending_device.json"


def _get_pending_path(profile: str | None = None) -> str:
    """Get path to the pending device code file for the active profile."""
    import os

    from upscaler_cli.profile import get_profile_dir

    config_dir = get_profile_dir(profile)
    return os.path.join(str(config_dir), _PENDING_FILE)


def _save_pending_device(data: dict, profile: str | None = None) -> None:
    """Save pending device code to disk (0600 — the device code is a credential)."""
    import os
    from pathlib import Path

    from upscaler_cli.profile import ensure_profile_dir
    from upscaler_cli.security import write_private_text

    path = _get_pending_path(profile)
    ensure_profile_dir(Path(os.path.dirname(path)))
    write_private_text(Path(path), json.dumps(data))


def _load_pending_device(profile: str | None = None) -> dict | None:
    """Load pending device code from disk, or None if absent."""
    import os

    path = _get_pending_path(profile)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.loads(f.read())
    except (json.JSONDecodeError, OSError):
        return None


def _delete_pending_device(profile: str | None = None) -> None:
    """Remove the pending device code file."""
    import os

    path = _get_pending_path(profile)
    if os.path.exists(path):
        os.unlink(path)


@click.command()
@pass_context
def refresh(ctx):
    """Refresh an expired access token using the stored refresh token.

    Examples:
        upscaler refresh
        upscaler refresh --json
    """
    from upscaler_cli.auth.oauth import OAuthFlow
    from upscaler_cli.auth.token_store import TokenStore
    from upscaler_cli.config import CLIConfig

    config = CLIConfig(profile=ctx.profile)
    server_url = config.resolve_server_url(ctx.server_url)
    store = TokenStore(profile=ctx.profile)

    try:
        token_data = store.load()
    except RuntimeError as e:
        if ctx.json_mode:
            click.echo(json.dumps({"error": str(e), "exit_code": 2}), err=True)
        else:
            click.echo(str(e), err=True)
        sys.exit(2)

    try:
        verify_ssl = config.resolve_verify_ssl()
        flow = OAuthFlow(server_url or "", verify_ssl=verify_ssl)
        new_token_data = asyncio.run(flow.refresh(token_data))
        store.save(new_token_data)

        expires_in = int(new_token_data.expires_at - time.time())
        if ctx.json_mode:
            click.echo(json.dumps({"success": True, "data": {"expires_in": expires_in}}))
        else:
            click.echo(f"Token refreshed. Expires in {_format_duration(expires_in)}.")

    except RuntimeError as e:
        if ctx.json_mode:
            click.echo(json.dumps({"error": str(e), "exit_code": 2}), err=True)
        else:
            click.echo(str(e), err=True)
        sys.exit(2)


@click.command()
@pass_context
def status(ctx):
    """Show authentication status and token expiry.

    Examples:
        upscaler status
        upscaler --json status
    """
    from upscaler_cli.auth.token_store import TokenStore

    store = TokenStore(profile=ctx.profile)

    try:
        token_data = store.load()
    except RuntimeError:
        if ctx.json_mode:
            click.echo(json.dumps({"authenticated": False, "message": "Not authenticated"}))
        else:
            click.echo("Status: Not authenticated")
            click.echo("Run: upscaler login")
        return

    mode = "device" if token_data.client_id == "device" else "oauth"
    refresh_present = bool(token_data.refresh_token)

    if ctx.json_mode:
        expires_in = int(token_data.expires_at - time.time())
        click.echo(json.dumps({
            "authenticated": True,
            "expired": expires_in <= 0,
            "expires_in": max(0, expires_in),
            "organization_id": token_data.organization_id,
            "mode": mode,
            "refresh_token_present": refresh_present,
        }))
    else:
        expires_in = int(token_data.expires_at - time.time())
        click.echo(f"Status: Authenticated ({mode})")
        if token_data.organization_id:
            click.echo(f"Organization: {token_data.organization_id}")
        if expires_in <= 0:
            click.echo("Token: expired (run: upscaler refresh)")
        else:
            click.echo(f"Expires in: {_format_duration(expires_in)}")
        if refresh_present:
            click.echo("Refresh token: present")
        else:
            click.echo("Refresh token: missing (re-login required on expiry)")


@click.command()
@pass_context
def logout(ctx):
    """Revoke tokens and clear local storage.

    Examples:
        upscaler logout
    """
    from upscaler_cli.auth.oauth import OAuthFlow
    from upscaler_cli.auth.token_store import TokenStore
    from upscaler_cli.config import CLIConfig

    config = CLIConfig(profile=ctx.profile)
    server_url = config.resolve_server_url(ctx.server_url)
    store = TokenStore(profile=ctx.profile)

    try:
        token_data = store.load()
    except RuntimeError:
        # No tokens, but an interrupted device login may still have left a
        # redeemable device code behind; clear it before reporting.
        _delete_pending_device(ctx.profile)
        if ctx.json_mode:
            click.echo(json.dumps({"success": True, "message": "Not logged in."}))
        else:
            click.echo("Not logged in.")
        return

    # Best-effort server revocation
    if server_url:
        try:
            verify_ssl = config.resolve_verify_ssl()
            flow = OAuthFlow(server_url, verify_ssl=verify_ssl)
            asyncio.run(flow.revoke(token_data))
        except Exception:
            if not ctx.json_mode:
                click.echo(
                    "Logged out locally. Server revocation failed — "
                    "token will expire naturally.",
                    err=True,
                )

    store.delete()
    # A device code left over from an interrupted `login --no-browser` is still
    # redeemable for tokens until it expires, so logout must clear it too.
    _delete_pending_device(ctx.profile)

    if ctx.json_mode:
        click.echo(json.dumps({"success": True}))
    else:
        click.echo("Logged out successfully.")
