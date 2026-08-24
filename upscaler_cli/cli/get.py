"""Get asset, member, or group by ID."""

import asyncio
import sys

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, raise_on_envelope_error

# Prefix → (type, endpoint)
# NOTE: longer prefixes must come before shorter ones (e.g. "to_" before "t_")
_PREFIX_ROUTES = {
    "to_": ("todo", "/api/v1/todos"),
    "g_": ("group", "/api/v1/groups"),
    "t_": ("task", "/api/v1/tasks"),
}

# Known asset prefixes (routed to /api/v1/assets)
_ASSET_PREFIXES = ("d_", "doc_", "rg_", "rd_", "r_", "rec_", "i_", "cd_")

# Explicit --type → endpoint
_TYPE_ROUTES = {
    "member": "/api/v1/members",
    "group": "/api/v1/groups",
    "task": "/api/v1/tasks",
    "todo": "/api/v1/todos",
}


def _detect_route(resource_id, resource_type):
    """Detect the API route for a resource.

    Returns (endpoint_base, is_asset) or (None, None) if unknown.
    """
    # 1. Explicit --type takes priority
    if resource_type and resource_type in _TYPE_ROUTES:
        return _TYPE_ROUTES[resource_type], False

    # 2. Auto-detect by prefix
    for prefix, (_, endpoint) in _PREFIX_ROUTES.items():
        if resource_id.startswith(prefix):
            return endpoint, False

    for prefix in _ASSET_PREFIXES:
        if resource_id.startswith(prefix):
            return "/api/v1/assets", True

    # 3. Unknown
    return None, None


@click.command("get")
@click.argument("resource_id")
@click.option(
    "--format", "fmt", default=None,
    type=click.Choice(["json", "markdown", "schema"]),
    help="Output format: json (overview), markdown (content), schema (fields).",
)
@click.option(
    "--type", "resource_type", default=None,
    type=click.Choice(["member", "group", "task", "todo"]),
    help="Resource type (for IDs without a known prefix, e.g. member).",
)
@click.option(
    "--lane", default=None,
    type=click.Choice(["designer", "published"]),
    help="Which copy to read: published (default) or designer. Definition assets "
         "exist in both lanes under one id. Use designer when the result feeds an "
         "edit back, since content writes target the designer copy.",
)
@click.option(
    "--draft", is_flag=True, default=False,
    help="DEPRECATED, use --lane designer. Read the unpublished working copy "
         "instead of the published version.",
)
@pass_context
def get_asset(ctx, resource_id, fmt, resource_type, lane, draft):
    """Retrieve an asset, member, or group by ID.

    Asset and group IDs are auto-detected by prefix (rg_, d_, g_, etc.).
    For members, use --type member since member IDs have no prefix.

    Definition assets exist in two lanes sharing one id: the designer working
    copy and the published snapshot. Reads default to published; the response
    echoes which lane answered.

    Examples:
        upscaler get rg_abc123
        upscaler get rg_abc123 --format schema
        upscaler get rg_abc123 --lane designer
        upscaler get g_abc123
        upscaler get <uid> --type member
        upscaler --json get <uid> --type member
    """
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json

    client = make_client(ctx)

    endpoint, is_asset = _detect_route(resource_id, resource_type)

    if endpoint is None:
        if resource_id.startswith("cl_"):
            # Lessons are not standalone assets: they live inside a course and
            # are read through it. `get <cd_…>` returns every lesson with its
            # id, title, description, and body.
            msg = (
                f"{resource_id} is a lesson, which is read through its course. "
                "Run `upscaler get <cd_…>` to see every lesson (id, title, body)."
            )
        else:
            msg = (
                f"Unknown resource ID format: {resource_id}. "
                "Use --type member or --type group for IDs without a known prefix."
            )
        if ctx.json_mode:
            import json
            click.echo(json.dumps({"error": msg, "exit_code": 1}), err=True)
        else:
            click.echo(msg, err=True)
        sys.exit(1)
        return

    if is_asset:
        _get_asset(ctx, client, resource_id, fmt, format_json, lane=lane, draft=draft)
    else:
        _get_simple(ctx, client, f"{endpoint}/{resource_id}", format_json)


def _get_asset(ctx, client, asset_id, fmt, format_json, lane=None, draft=False):
    """Fetch and display an asset with format control."""
    params = {}
    # Only send a selector the caller actually set, so the server applies its own
    # default rather than this client hard-coding one.
    if lane:
        params["lane"] = lane
    if draft:
        params["draft"] = "true"
    if fmt:
        params["format"] = fmt

    try:
        result = asyncio.run(
            client.request("GET", f"/api/v1/assets/{asset_id}", params=params)
        )
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    data = result.get("data", {})

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    elif fmt == "markdown":
        content = data.get("markdown", data.get("text", ""))
        if content:
            click.echo(content)
        else:
            click.echo("No markdown content for this asset type.", err=True)
    elif fmt == "schema":
        schema = data.get("schema", {})
        if schema:
            click.echo(format_json(schema))
        else:
            click.echo("No schema available for this asset type.", err=True)
    else:
        click.echo(format_json(data))


def _get_simple(ctx, client, endpoint, format_json):
    """Fetch and display a simple resource (member, group)."""
    try:
        result = asyncio.run(client.request("GET", endpoint))
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    data = result.get("data", {})

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        click.echo(format_json(data))
