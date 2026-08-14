"""Comment CLI commands: list, add, edit, delete comments (A093).

Backs the up-ai REST comment routes. Local validation (allow-list, content
length, mention format) mirrors the native layer so obvious mistakes fail fast
with no HTTP round-trip. The server remains the source of truth and enforces
edit/delete authorization: only the author may edit; only the author or an
org admin/owner may delete.
"""

import asyncio
import re

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import (
    emit_action_result,
    handle_error,
    make_client,
    raise_on_envelope_error,
)
from upscaler_cli.errors import CLIError
from upscaler_cli.formatters.json_fmt import format_json

# Mirror of the native allow-list / limits for fast client-side feedback.
_ALLOWED_ASSET_TYPES = {"todo", "release"}
_MAX_CONTENT_LENGTH = 2000
_MENTION_RE = re.compile(r"^(?:member|group)::.+$")


@click.group("comment")
def comment_group():
    """Read, add, edit, and delete comments on todos and releases.

    Examples:
        upscaler comment list --asset-id to_123 --asset-type todo
        upscaler comment add --asset-id to_123 --asset-type todo \\
            --content "Looks good" --mention member::m_1
        upscaler comment edit --comment-id co_123 --content "Revised" \\
            --mention member::m_2
        upscaler comment delete co_123
    """
    pass


def _check_asset_type(asset_type):
    if asset_type not in _ALLOWED_ASSET_TYPES:
        raise CLIError(
            f"asset_type '{asset_type}' is not supported. Use 'todo' or 'release'."
        )


@comment_group.command("list")
@click.option("--asset-id", required=True, help="Asset id the thread belongs to.")
@click.option("--asset-type", required=True, help="'todo' or 'release'.")
@click.option("--context-id", default=None, help="Optional sub-context id.")
@click.option("--limit", default=20, type=int, help="Max comments to return.")
@click.option("--offset", default=0, type=int, help="Offset for pagination.")
@pass_context
def comment_list(ctx, asset_id, asset_type, context_id, limit, offset):
    """List comments on a todo or release."""
    try:
        _check_asset_type(asset_type)
    except CLIError as e:
        handle_error(ctx, e)
        return

    params = {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "limit": limit,
        "offset": offset,
    }
    if context_id:
        params["context_id"] = context_id

    client = make_client(ctx)
    try:
        result = asyncio.run(client.request("GET", "/api/v1/comments", params=params))
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
        return

    comments = (result.get("data") or {}).get("comments", [])
    if not comments:
        click.echo("No comments.")
        return
    for c in comments:
        author = (c.get("author") or {}).get("name") or "unknown"
        click.echo(f"[{c.get('createdAt', '')}] {author}: {c.get('content', '')}")


@comment_group.command("add")
@click.option("--asset-id", required=True, help="Asset id the thread belongs to.")
@click.option("--asset-type", required=True, help="'todo' or 'release'.")
@click.option(
    "--content",
    required=True,
    help=(
        "Comment body (max 2000 chars). '@[member::<id>]' placeholders (and "
        "exact directory names like '@Jane Doe') are expanded server-side to "
        "mention chips, and the mention list is derived from them."
    ),
)
@click.option(
    "--mention",
    "mentions",
    multiple=True,
    help="Typed mention id 'member::<id>' or 'group::<id>'. Repeatable.",
)
@click.option("--context-id", default=None, help="Optional sub-context id.")
@pass_context
def comment_add(ctx, asset_id, asset_type, content, mentions, context_id):
    """Add a comment. Mentions fire real notifications, as in the web app."""
    try:
        _check_asset_type(asset_type)
        if len(content) > _MAX_CONTENT_LENGTH:
            raise CLIError(
                f"Content exceeds {_MAX_CONTENT_LENGTH} characters ({len(content)})."
            )
        bad = [m for m in mentions if not _MENTION_RE.match(m)]
        if bad:
            raise CLIError(
                f"Malformed mention(s): {list(bad)}. Use 'member::<id>' or 'group::<id>'."
            )
    except CLIError as e:
        handle_error(ctx, e)
        return

    payload = {"asset_id": asset_id, "asset_type": asset_type, "content": content}
    if mentions:
        payload["mentions"] = list(mentions)
    if context_id:
        payload["context_id"] = context_id

    client = make_client(ctx)
    try:
        result = asyncio.run(client.request("POST", "/api/v1/comments", json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    emit_action_result(ctx, result, label="Comment added")


def _validate_content_and_mentions(content, mentions):
    """Shared fail-fast validation for add/edit. Raises CLIError."""
    if len(content) > _MAX_CONTENT_LENGTH:
        raise CLIError(
            f"Content exceeds {_MAX_CONTENT_LENGTH} characters ({len(content)})."
        )
    bad = [m for m in mentions if not _MENTION_RE.match(m)]
    if bad:
        raise CLIError(
            f"Malformed mention(s): {list(bad)}. Use 'member::<id>' or 'group::<id>'."
        )


@comment_group.command("edit")
@click.option("--comment-id", required=True, help="Comment id to edit (author only).")
@click.option("--content", required=True, help="New comment body (max 2000 chars).")
@click.option(
    "--mention",
    "mentions",
    multiple=True,
    help=(
        "Replace stored mentions with these typed ids ('member::<id>' / "
        "'group::<id>'). Repeatable. Omit to leave stored mentions unchanged; "
        "only NEWLY-added mentions are notified."
    ),
)
@click.option(
    "--clear-mentions",
    is_flag=True,
    help="Remove all mentions from the comment (mutually exclusive with --mention).",
)
@pass_context
def comment_edit(ctx, comment_id, content, mentions, clear_mentions):
    """Edit a comment you authored. The server rejects edits of others' comments."""
    try:
        if mentions and clear_mentions:
            raise CLIError("--mention and --clear-mentions are mutually exclusive.")
        _validate_content_and_mentions(content, mentions)
    except CLIError as e:
        handle_error(ctx, e)
        return

    payload = {"action": "edit", "comment_id": comment_id, "content": content}
    if clear_mentions:
        payload["mentions"] = []
    elif mentions:
        payload["mentions"] = list(mentions)

    client = make_client(ctx)
    try:
        result = asyncio.run(client.request("POST", "/api/v1/comments", json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    emit_action_result(ctx, result, label="Comment updated")


@comment_group.command("delete")
@click.argument("comment_id")
@click.option("--dry-run", is_flag=True, help="Preview without deleting.")
@pass_context
def comment_delete(ctx, comment_id, dry_run):
    """Soft-delete a comment (author, or org admin/owner)."""
    from upscaler_cli.cli.helpers import confirm_destructive

    payload = {"action": "delete", "comment_id": comment_id}

    if dry_run:
        if ctx.json_mode:
            click.echo(format_json({"dry_run": True, "payload": payload}, compact=True))
        else:
            click.echo("[dry-run] Would delete comment:")
            click.echo(format_json(payload))
        return

    if not confirm_destructive("delete", comment_id, ctx.json_mode):
        click.echo("Cancelled.", err=True)
        return

    client = make_client(ctx)
    try:
        result = asyncio.run(client.request("POST", "/api/v1/comments", json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    emit_action_result(ctx, result, label="Comment deleted")
