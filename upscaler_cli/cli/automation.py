"""Automation management CLI commands.

Lists, inspects, and manages automations (scheduled actions on assets/members).
Wraps POST /api/v1/automations on the up-ai REST API.
"""

import sys

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import execute_rest_action


@click.group("automation")
def automation_group():
    """Manage automations: list, get, create, update, enable, disable, run, delete, runs.

    Examples:
        upscaler automation list
        upscaler automation get auto_abc123
        upscaler automation create --data @automation.json
        upscaler automation enable auto_abc123
        upscaler automation run auto_abc123
        upscaler automation runs auto_abc123 --limit 50
        upscaler automation list --asset-id d_xyz
    """
    pass


@automation_group.command("list")
@click.option("--search", default=None, help="Search filter.")
@click.option(
    "--action-type",
    "action_types",
    multiple=True,
    help=(
        "Filter by action type (repeatable): createTodo, createRecord, "
        "sendEmailDigest, createReviewRequest"
    ),
)
@click.option(
    "--asset-id",
    default=None,
    help="If given, list automations bound to this asset (uses getAssetAutomations).",
)
@click.option("--upcoming", is_flag=True, help="Show only upcoming automations.")
@click.option("--limit", default=50, type=int, help="Page size (default 50).")
@click.option("--offset", default=0, type=int, help="Page offset (default 0).")
@pass_context
def automation_list(ctx, search, action_types, asset_id, upcoming, limit, offset):
    """List automations."""
    if upcoming and asset_id:
        click.echo("--upcoming and --asset-id are mutually exclusive", err=True)
        sys.exit(1)

    if asset_id:
        action = "list_for_asset"
        payload = {"action": action, "asset_id": asset_id, "limit": limit, "offset": offset}
    elif upcoming:
        action = "list_upcoming"
        payload = {"action": action, "limit": limit, "offset": offset}
    else:
        action = "list"
        payload = {"action": action, "limit": limit, "offset": offset}
        if search:
            payload["search"] = search
        if action_types:
            payload["action_types"] = list(action_types)

    _execute(ctx, payload)


@automation_group.command("get")
@click.argument("automation_id")
@pass_context
def automation_get(ctx, automation_id):
    """Fetch a single automation by ID."""
    _execute(ctx, {"action": "get", "id": automation_id})


@automation_group.command("runs")
@click.argument("automation_id")
@click.option("--limit", default=20, type=int)
@click.option("--offset", default=0, type=int)
@pass_context
def automation_runs(ctx, automation_id, limit, offset):
    """List recent runs of an automation."""
    _execute(
        ctx,
        {"action": "list_runs", "id": automation_id, "limit": limit, "offset": offset},
    )


@automation_group.command("create")
@click.option(
    "--data",
    "data_input",
    required=True,
    help="JSON payload (value, - for stdin, @file).",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@pass_context
def automation_create(ctx, data_input, dry_run):
    """Create an automation.

    --data should be CreateAutomationInput shape, e.g.:
    {"title": "Weekly review", "trigger": {"type": "schedule",
     "schedule": {"cron": "0 9 * * 1", "timezone": "UTC"}},
     "target": {"type": "asset", "asset": {"id": "d_xxx", "type": "document"}},
     "action": {"type": "createTodo", "createTodo":
       {"title": "Review doc", "assignees": ["user_abc"]}}}
    """
    from upscaler_cli.cli.helpers import parse_data

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    _execute(ctx, {"action": "create", "data": data}, dry_run=dry_run)


@automation_group.command("update")
@click.argument("automation_id")
@click.option("--data", "data_input", required=True, help="JSON payload.")
@click.option("--dry-run", is_flag=True)
@pass_context
def automation_update(ctx, automation_id, data_input, dry_run):
    """Update an automation."""
    from upscaler_cli.cli.helpers import parse_data

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    _execute(ctx, {"action": "update", "id": automation_id, "data": data}, dry_run=dry_run)


@automation_group.command("enable")
@click.argument("automation_id")
@pass_context
def automation_enable(ctx, automation_id):
    """Enable an automation."""
    _execute(ctx, {"action": "enable", "id": automation_id})


@automation_group.command("disable")
@click.argument("automation_id")
@pass_context
def automation_disable(ctx, automation_id):
    """Disable an automation."""
    _execute(ctx, {"action": "disable", "id": automation_id})


@automation_group.command("run")
@click.argument("automation_id")
@pass_context
def automation_run(ctx, automation_id):
    """Manually trigger an automation now."""
    _execute(ctx, {"action": "run", "id": automation_id})


@automation_group.command("delete")
@click.argument("automation_id")
@click.option("--dry-run", is_flag=True)
@pass_context
def automation_delete(ctx, automation_id, dry_run):
    """Delete an automation."""
    from upscaler_cli.cli.helpers import confirm_destructive

    if not dry_run and not confirm_destructive("delete", automation_id, ctx.json_mode):
        click.echo("Cancelled.", err=True)
        return

    _execute(ctx, {"action": "delete", "id": automation_id}, dry_run=dry_run)


def _execute(ctx, payload, dry_run=False):
    execute_rest_action(
        ctx, payload, "/api/v1/automations", render=_render_human, dry_run=dry_run
    )


def _render_human(action, result):
    from upscaler_cli.formatters.json_fmt import format_json

    if not result.get("success"):
        click.echo(format_json(result))
        return

    data = result.get("data")
    meta = result.get("metadata") or {}

    if isinstance(data, list):
        if not data:
            click.echo("(no results)")
            return
        for item in data:
            if isinstance(item, dict):
                if "triggeredAt" in item or "scheduleId" in item:
                    click.echo(
                        f"{item.get('triggeredAt', '')}  {item.get('status', ''):8}  "
                        f"{item.get('resultTitle', '') or item.get('id', '')}"
                    )
                else:
                    enabled = "on " if item.get("enabled") else "off"
                    next_due = item.get("nextDue") or ""
                    click.echo(
                        f"{item.get('id', ''):28}  [{enabled}]  "
                        f"{item.get('title', '') or '(untitled)':40}  next: {next_due}"
                    )
        if meta.get("total_count") is not None:
            click.echo(f"\nTotal: {meta['total_count']} (showing {len(data)})")
    elif isinstance(data, dict):
        click.echo(format_json(data))
    else:
        click.echo(str(data))
