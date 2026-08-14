"""Hierarchy command for asset tree view."""

import asyncio

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, raise_on_envelope_error


@click.command()
@click.argument("asset_id")
@click.option("--depth", default=3, help="Max depth to traverse.")
@click.option("--include-siblings", is_flag=True, help="Include sibling nodes.")
@pass_context
def hierarchy(ctx, asset_id, depth, include_siblings):
    """View an asset's hierarchy as an indented tree.

    Examples:
        upscaler hierarchy abc123
        upscaler hierarchy abc123 --depth 5 --include-siblings
        upscaler --json hierarchy abc123
    """
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json
    from upscaler_cli.formatters.tree import format_tree

    client = make_client(ctx)

    params = {"depth": depth, "include_siblings": include_siblings}

    try:
        result = asyncio.run(
            client.request("GET", f"/api/v1/hierarchy/{asset_id}", params=params)
        )
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        data = result.get("data", {})
        click.echo(format_tree(data))
