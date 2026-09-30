"""Shared helpers for CLI commands."""

import json
import sys
from pathlib import Path

from upscaler_cli.errors import CLIError


def parse_data(value: str) -> dict:
    """Parse --data flag value into a dict.

    Supports three input forms:
    - Flag value: --data '{"json": true}'
    - Stdin pipe: --data -
    - File reference: --data @file.json

    Args:
        value: The --data flag value.

    Returns:
        Parsed dict.

    Raises:
        CLIError: On invalid JSON, missing file, or TTY stdin.
    """
    if value == "-":
        # Stdin
        if sys.stdin.isatty():
            print("Reading JSON from stdin (Ctrl+D to end):", file=sys.stderr)
        raw = sys.stdin.read()
    elif value.startswith("@"):
        # File reference
        file_path = Path(value[1:])
        if not file_path.exists():
            raise CLIError(f"File not found: {file_path}")
        raw = file_path.read_text()
    else:
        # Direct value
        raw = value

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CLIError(f"Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise CLIError("--data must be a JSON object (dict)")

    return data


def build_values_payload(data_input, values_file, values_type) -> dict:
    """Build the ``{"values": ...}`` payload for a ``set-*-values`` command.

    Content comes from exactly one of ``--data`` or ``--values-file``. A
    ``--values-file`` is read as a markdown string, or parsed as a JSON Slate
    body when ``--values-type`` is not ``markdown`` (packing slateJson as a raw
    string sends a string where the platform expects a list, which it silently
    drops, so a malformed file must fail loudly). On any usage error this prints
    to stderr and exits non-zero, matching the rest of the CLI.

    Args:
        data_input: The ``--data`` flag value (or None).
        values_file: The ``--values-file`` path (or None).
        values_type: The ``--values-type`` value (e.g. "markdown", "slateJson").

    Returns:
        A dict with a ``values`` key, ready for the command's id/valuesType keys.
    """
    import click

    if not data_input and not values_file:
        click.echo("Provide either --data or --values-file.", err=True)
        sys.exit(1)
    if data_input and values_file:
        click.echo("--data and --values-file are mutually exclusive.", err=True)
        sys.exit(1)

    if values_file:
        raw = Path(values_file).read_text()
        if values_type == "markdown":
            values = raw
        else:
            try:
                values = json.loads(raw)
            except json.JSONDecodeError as e:
                click.echo(
                    f"--values-file expects a JSON Slate body for --values-type "
                    f"slateJson, but {values_file} is not valid JSON: {e}",
                    err=True,
                )
                sys.exit(1)
        return {"values": values}

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if "values" not in data:
        click.echo("--data must include a 'values' key.", err=True)
        sys.exit(1)
    return data


def validate_entry_data(data: dict) -> dict:
    """Reject entry payloads that put ff_* keys at the top level.

    The REST `/entries` endpoint reads form-field values exclusively from
    `data.values`. Bare `{"ff_x": ...}` payloads slip through the request
    parser (success response, entry id returned) but the values are silently
    dropped on the server side. Surface this as a usage error so the caller
    gets a hint pointing at the canonical wrapper shape.
    """
    if not isinstance(data, dict):
        return data
    stray = sorted(k for k in data.keys() if isinstance(k, str) and k.startswith("ff_"))
    if not stray:
        return data
    keys = ", ".join(stray)
    raise CLIError(
        f"Top-level form-field keys ({keys}) would be dropped by the server. "
        f'Wrap them in a `values` object, e.g. {{"values": {{"{stray[0]}": ...}}}}.'
    )


def handle_error(ctx, e) -> None:
    """Handle CLI errors with appropriate output mode and exit code.

    Args:
        ctx: CLI Context with json_mode flag.
        e: Exception to handle.
    """
    import click

    exit_code = getattr(e, "exit_code", 1)
    if ctx.json_mode:
        click.echo(json.dumps({"error": str(e), "exit_code": exit_code}), err=True)
    else:
        click.echo(str(e), err=True)
    sys.exit(exit_code)


def raise_on_envelope_error(ctx, result) -> None:
    """Exit with the server's error when a read returns a failure envelope.

    The REST API returns HTTP 200 with {"success": false, "error": {...},
    "data": []} for failures the native tools catch internally (e.g. missing
    organization context). `client.request` only raises on HTTP >= 400, so these
    slip through to read commands that look only at `data` and render the empty
    result as "No results". Mirror the write-path guard (emit_action_result) so
    reads fail loudly and exit non-zero too. Only an explicit `success: false`
    triggers this; success responses (success true or absent) pass through.
    """
    if isinstance(result, dict) and result.get("success") is False:
        handle_error(ctx, CLIError(_envelope_error_message(result.get("error"))))


def _resolve_id(data: dict, id_keys) -> str:
    """Return the first non-empty id value among id_keys, or ''."""
    for key in id_keys:
        value = (data or {}).get(key)
        if value:
            return value
    return ""


_RESULT_ID_KEYS = ("id", "entryId", "entry_id", "assetId", "asset_id")


def _envelope_error_message(error) -> str:
    """Extract a human-readable message from a native-tool error envelope.

    `error` is the unified envelope dict ({error_code, message, ...}) on most
    failures, but tolerate a bare string or missing value too.
    """
    if isinstance(error, dict):
        return error.get("message") or error.get("error_code") or "Operation failed"
    if error:
        return str(error)
    return "Operation failed"


def emit_action_result(ctx, result: dict, *, label: str, id_keys=_RESULT_ID_KEYS) -> None:
    """Print the outcome of a create/update mutation, honoring --quiet/--json.

    quiet : print only the resolved id (one line); nothing else.
    json  : print the full compact envelope.
    human : print "<label>: <id>".

    A native-tool envelope can report failure with HTTP 200
    ({"success": false, "error": {...}}); surface that error and exit non-zero
    instead of printing an empty id.
    """
    import click

    from upscaler_cli.formatters.json_fmt import format_json

    if result.get("success") is False:
        if ctx.json_mode:
            click.echo(format_json(result, compact=True), err=True)
        else:
            click.echo(f"{label} failed: {_envelope_error_message(result.get('error'))}", err=True)
        sys.exit(1)
        return

    if getattr(ctx, "quiet_mode", False):
        rid = _resolve_id(result.get("data", {}), id_keys)
        if rid:
            click.echo(rid)
            return
        # --quiet promises the resolved id on stdout. A success envelope with no
        # id key would otherwise emit empty stdout and exit 0, silently breaking
        # callers that capture the id. Fail loud instead.
        click.echo(f"{label}: succeeded but returned no id", err=True)
        sys.exit(1)
        return
    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        rid = _resolve_id(result.get("data", {}), id_keys)
        click.echo(f"{label}: {rid}")


def emit_dry_run(ctx, *, summary: str, payload: dict) -> None:
    """Print a dry-run preview, honoring --quiet/--json.

    quiet : print only the one-line summary (no body).
    json  : print {"dry_run": true, "payload": ...} compact.
    human : print the summary line followed by the pretty payload.
    """
    import click

    from upscaler_cli.formatters.json_fmt import format_json

    if getattr(ctx, "quiet_mode", False):
        click.echo(f"[dry-run] {summary}")
        return
    if ctx.json_mode:
        click.echo(format_json({"dry_run": True, "payload": payload}, compact=True))
    else:
        click.echo(f"[dry-run] {summary}")
        click.echo(format_json(payload))


def make_client(ctx):
    """Create an UpscalerClient from CLI context.

    Centralizes config resolution and client construction.

    Args:
        ctx: CLI Context with server_url and verbose flags.

    Returns:
        Configured UpscalerClient instance.
    """
    from upscaler_cli.auth.token_store import TokenStore
    from upscaler_cli.client import UpscalerClient
    from upscaler_cli.config import CLIConfig

    profile = getattr(ctx, "profile", None)
    config = CLIConfig(profile=profile)
    server_url = config.resolve_server_url(ctx.server_url)
    verify_ssl = config.resolve_verify_ssl()
    warn_if_insecure_transport(server_url, verify_ssl)
    return UpscalerClient(
        server_url,
        TokenStore(profile=profile),
        verbose=ctx.verbose,
        verify_ssl=verify_ssl,
    )


_INSECURE_WARNED = set()


def warn_if_insecure_transport(server_url: str, verify_ssl: bool) -> None:
    """Warn on stderr when the bearer token would travel unprotected.

    Both conditions are opt-in (`config set verify_ssl false`, or an http://
    server URL) and both are legitimate against a local dev server — but they
    are silent today, so a config left over from a debugging session keeps
    shipping the access token in the clear with nothing on screen to say so.
    Warned once per (url, mode) per process to stay usable in loops; stderr
    only, so --json stdout stays machine-parseable.
    """
    import click

    scheme = (server_url or "").split("://", 1)[0].lower()
    if scheme == "http":
        key = ("http", server_url)
        if key not in _INSECURE_WARNED:
            _INSECURE_WARNED.add(key)
            click.echo(
                f"Warning: {server_url} uses plaintext HTTP — your access token is "
                "sent unencrypted and is readable by anyone on the network path.",
                err=True,
            )
    elif not verify_ssl:
        key = ("noverify", server_url)
        if key not in _INSECURE_WARNED:
            _INSECURE_WARNED.add(key)
            click.echo(
                f"Warning: TLS certificate verification is disabled for {server_url}. "
                "The connection is not protected against interception. "
                "Unset with: upscaler config set verify_ssl true",
                err=True,
            )


def confirm_destructive(operation: str, resource_id: str, json_mode: bool) -> bool:
    """Prompt for confirmation on destructive operations.

    Silent (returns True) when piped or in --json mode.

    Args:
        operation: Operation name (e.g., "delete").
        resource_id: ID of the resource being affected.
        json_mode: If True, skip confirmation.

    Returns:
        True if confirmed, False otherwise.
    """
    if json_mode or not sys.stdout.isatty():
        return True

    response = input(f"Confirm {operation} {resource_id}? [y/N] ")
    return response.lower() in ("y", "yes")


def execute_rest_action(ctx, payload: dict, endpoint: str, render=None, dry_run: bool = False):
    """Run a POST against a REST endpoint and emit JSON or human output.

    Shared by action-based CLI groups (todo, automation, framework, ...) that
    all serialize their command as `{"action": "...", ...}` to a single
    endpoint and print either the raw envelope (JSON mode) or a domain-tuned
    summary (human mode).

    Args:
        ctx: CLI Context (json_mode, server_url, verbose).
        payload: JSON-serializable request body.
        endpoint: REST path, e.g. "/api/v1/automations".
        render: Optional callable(action, result) for human output. If None,
                falls back to the raw envelope.
        dry_run: When True, prints the payload that WOULD be sent and exits.
    """
    import asyncio

    import click

    from upscaler_cli.formatters.json_fmt import format_json

    if dry_run:
        if ctx.json_mode:
            click.echo(format_json({"dry_run": True, "payload": payload}, compact=True))
        else:
            click.echo(f"[dry-run] Would call POST {endpoint} with:")
            click.echo(format_json(payload))
        return

    client = make_client(ctx)
    try:
        result = asyncio.run(client.request("POST", endpoint, json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
        return

    if render:
        render(payload.get("action"), result)
    else:
        click.echo(format_json(result))
