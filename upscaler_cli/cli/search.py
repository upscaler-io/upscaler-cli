"""Search command for document search."""

import asyncio

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, raise_on_envelope_error


@click.command()
@click.argument("query")
@click.option("--limit", default=10, help="Number of results to return.")
@click.option(
    "--type",
    "asset_type",
    default=None,
    help="Filter by asset type (raw enum, e.g. document_definition, item).",
)
@click.option(
    "--parent-id",
    "parent_id",
    default=None,
    help="Restrict the search to descendants of this asset (e.g. the ISMS root d_*).",
)
@click.option(
    "--published-after",
    "published_after",
    default=None,
    help="Only results published on/after this ISO 8601 date (e.g. 2025-01-01).",
)
@click.option(
    "--published-before",
    "published_before",
    default=None,
    help="Only results published on/before this ISO 8601 date.",
)
@click.option("--tag", "tags", multiple=True, help="Filter by tag id (repeatable).")
@click.option(
    "--sort-by",
    "sort_by",
    default=None,
    type=click.Choice(["relevance", "date", "title"]),
    help="Sort order (default: relevance).",
)
@click.option(
    "--score-threshold",
    "score_threshold",
    default=None,
    type=float,
    help="Minimum relevance score (0.0-1.0).",
)
@click.option(
    "--include-metadata/--no-include-metadata",
    "include_metadata",
    default=False,
    help=(
        "Include the per-result raw chunk metadata block. Off by default "
        "(lean response); turn on only when you need raw chunk metadata."
    ),
)
@pass_context
def search(
    ctx,
    query,
    limit,
    asset_type,
    parent_id,
    published_after,
    published_before,
    tags,
    sort_by,
    score_threshold,
    include_metadata,
):
    """Search Upscaler documents.

    Hybrid semantic + keyword search over document AND register-entry content.
    Results are embedding chunks: cite by ``asset_id`` (not the top-level ``id``)
    and de-duplicate by ``asset_id``.

    Examples:
        upscaler search "safety procedures"
        upscaler search "compliance" --limit 5 --type document_definition
        upscaler search "access control" --parent-id d_isms --published-after 2025-01-01
        upscaler --json search "audit"
    """
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json
    from upscaler_cli.formatters.table import format_table

    client = make_client(ctx)

    # Build the request body. Send only the params the caller set so the
    # server's defaults apply to everything else. The REST /api/v1/search
    # model accepts all of these (SearchBase).
    body = {"query": query, "limit": limit, "include_metadata": include_metadata}
    if asset_type is not None:
        body["asset_type"] = asset_type
    if parent_id is not None:
        body["parent_id"] = parent_id
    if published_after is not None:
        body["published_after"] = published_after
    if published_before is not None:
        body["published_before"] = published_before
    if tags:
        body["tags"] = list(tags)
    if sort_by is not None:
        body["sort_by"] = sort_by
    if score_threshold is not None:
        body["score_threshold"] = score_threshold

    try:
        result = asyncio.run(client.request("POST", "/api/v1/search", json=body))
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        data = result.get("data", [])
        if not data:
            click.echo("No results found.")
            return
        click.echo(format_table(
            data,
            columns=["score", "asset_id", "asset_title", "asset_type"],
        ))
