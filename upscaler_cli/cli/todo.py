"""Todo management CLI commands."""

import asyncio

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, raise_on_envelope_error


@click.group("todo")
def todo_group():
    """Manage todos: create, update, close, reopen, delete.

    Examples:
        upscaler todo create --title "Review doc" --assignee user123
        upscaler todo close abc123
        upscaler todo delete abc123 --dry-run
    """
    pass


@todo_group.command("create")
@click.option("--title", required=True, help="Todo title.")
@click.option("--assignee", default=None, help="Assignee user ID.")
@click.option("--due", "due_date", default=None, help="Due date (ISO 8601).")
@click.option(
    "--bookmark-url",
    "bookmark_url",
    default=None,
    help="In-app path the todo's View link points to, e.g. /document/d_123.",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@pass_context
def todo_create(ctx, title, assignee, due_date, bookmark_url, dry_run):
    """Create a new todo."""
    data = {"title": title}
    if assignee:
        data["assignees"] = [assignee]
    if due_date:
        data["dueDateTime"] = due_date
    if bookmark_url:
        data["bookmarkUrl"] = bookmark_url

    _execute_todo(ctx, "create", data=data, dry_run=dry_run)


@todo_group.command("update")
@click.argument("todo_id")
@click.option("--title", default=None, help="New title.")
@click.option("--assignee", default=None, help="New assignee.")
@click.option("--due", "due_date", default=None, help="New due date.")
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def todo_update(ctx, todo_id, title, assignee, due_date, dry_run):
    """Update an existing todo."""
    data = {}
    if title:
        data["title"] = title
    if assignee:
        data["assignees"] = [assignee]
    if due_date:
        data["dueDateTime"] = due_date

    _execute_todo(ctx, "update", todo_id=todo_id, data=data, dry_run=dry_run)


@todo_group.command("close")
@click.argument("todo_id")
@pass_context
def todo_close(ctx, todo_id):
    """Close a todo."""
    _execute_todo(ctx, "close", todo_id=todo_id)


@todo_group.command("reopen")
@click.argument("todo_id")
@pass_context
def todo_reopen(ctx, todo_id):
    """Reopen a closed todo."""
    _execute_todo(ctx, "reopen", todo_id=todo_id)


@todo_group.command("delete")
@click.argument("todo_id")
@click.option("--dry-run", is_flag=True, help="Preview without deleting.")
@pass_context
def todo_delete(ctx, todo_id, dry_run):
    """Delete a todo."""
    from upscaler_cli.cli.helpers import confirm_destructive

    if not dry_run and not confirm_destructive("delete", todo_id, ctx.json_mode):
        click.echo("Cancelled.", err=True)
        return

    _execute_todo(ctx, "delete", todo_id=todo_id, dry_run=dry_run)


def _execute_todo(ctx, operation, todo_id=None, data=None, dry_run=False):
    """Execute a todo operation."""
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json

    payload = {"operation": operation}
    if todo_id:
        payload["id"] = todo_id
    if data:
        payload["data"] = data

    if dry_run:
        if ctx.json_mode:
            click.echo(format_json({"dry_run": True, "payload": payload}, compact=True))
        else:
            click.echo(f"[dry-run] Would {operation} todo:")
            click.echo(format_json(payload))
        return

    client = make_client(ctx)

    try:
        result = asyncio.run(client.request("POST", "/api/v1/todos", json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        d = result.get("data", {})
        click.echo(f"Todo {operation}d: {d.get('id', '')} — {d.get('title', '')}")
