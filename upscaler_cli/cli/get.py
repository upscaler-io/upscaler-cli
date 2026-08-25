"""Get asset, member, or group by ID."""

import asyncio
import sys

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, raise_on_envelope_error

# Prefix → (type, endpoint)
# No prefix here may be a prefix of another; if that changes, order longer first.
_PREFIX_ROUTES = {
    "g_": ("group", "/api/v1/groups"),
    "t_": ("task", "/api/v1/tasks"),
}

# Known asset prefixes (routed to /api/v1/assets). Mirrors _detect_asset_type's
# prefix_map in up-ai/src/tools/native/_helpers.py; keep the two in step.
# `to_` sits here, not in _PREFIX_ROUTES: todos are assets and share the shape.
# `bd_` is absent on purpose, even though recover.py handles it: the server has
# no board entry in prefix_map, so routing one here would only move the failure.
_ASSET_PREFIXES = ("d_", "doc_", "rg_", "rd_", "r_", "rec_", "i_", "cd_", "to_")

# Explicit --type → endpoint, for ids whose prefix cannot identify them.
_TYPE_ROUTES = {
    "member": "/api/v1/members",
    "group": "/api/v1/groups",
    "task": "/api/v1/tasks",
    # DEPRECATED: `to_` ids now route to /api/v1/assets, which honours --format
    # and --lane. This bare-object endpoint stays one release for scripts.
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


_FORMATS = ("json", "markdown", "schema")


def _parse_formats(ctx, param, value):
    """Accept --format repeated and/or comma-separated; duplicates collapse.

    Validated here rather than by click.Choice because type conversion runs
    before the callback, so "json,schema" would be rejected before the split.
    The server does not reject unknown format names (it returns an empty data
    object), so this is the only place a typo fails loudly.
    """
    names = [n.strip() for chunk in value for n in chunk.split(",") if n.strip()]
    for name in names:
        if name not in _FORMATS:
            raise click.BadParameter(f"{name!r} is not one of {', '.join(_FORMATS)}.")
    return tuple(dict.fromkeys(names))


@click.command("get")
@click.argument("resource_id")
@click.option(
    "--format", "fmt", multiple=True, callback=_parse_formats,
    help="Output formats: json (overview), markdown (content), schema (fields). "
         "Repeatable, and accepts a comma-separated list.",
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
        upscaler get rg_abc123 --format json,schema
        upscaler get rg_abc123 --lane designer
        upscaler get g_abc123
        upscaler get <uid> --type member
        upscaler --json get <uid> --type member
    """
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json

    if lane and draft:
        # The server gives `draft` precedence, so `--lane published --draft`
        # would quietly answer with the designer copy. Fail rather than
        # contradict what was asked for.
        raise click.UsageError(
            "--draft is the deprecated spelling of --lane designer; pass one, not both."
        )

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
        params["format"] = ",".join(fmt)

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
        return

    requested = fmt or ("json",)
    # Label sections only when there is more than one, so a single
    # --format markdown still prints the bare body and stays pipeable.
    label = len(requested) > 1
    for name in requested:
        if name == "markdown":
            body = data.get("markdown", data.get("text", ""))
            missing = "No markdown content for this asset type."
        elif name == "schema":
            schema = data.get("schema", {})
            body = format_json(schema) if schema else ""
            missing = "No schema available for this asset type."
        else:
            # The json section, not the whole envelope: with several formats the
            # envelope carries the other sections too and would print them twice.
            body = format_json(data.get("json", data))
            missing = "No json representation for this asset type."
        # Header follows its body's stream, so a piped stdout never collects a
        # section label with nothing under it.
        if label:
            click.echo(f"--- {name} ---", err=not body)
        click.echo(body or missing, err=not body)


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
