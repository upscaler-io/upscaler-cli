"""Recover CLI command: undo a soft-deletion (A093).

`upscaler recover <ASSET_ID>` restores a soft-deleted asset. `--dry-run` reports
the detected type and the backend mutation that would run, without any HTTP
call. Prefix routing mirrors the native `recover_asset` layer; the server is the
authority (an OWNER/ADMIN gate applies to the trash-fallback path).
"""

import asyncio
import re

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import emit_action_result, handle_error, make_client
from upscaler_cli.errors import CLIError

# (prefix, human type, backend mutation). Longest-prefix-first for dry-run.
_RECOVER_ROUTES = (
    ("doc_", "document", "recoverDocumentDefinition"),
    ("d_", "document", "recoverDocumentDefinition"),
    ("rg_", "register definition", "recoverRegisterDefinition"),
    ("i_", "item", "recoverItem"),
    ("rec_", "record", "recoverRecord"),
    ("r_", "record", "recoverRecord"),
    ("rd_", "record definition", "recoverRecordDefinition"),
    ("cd_", "course definition", "recoverCourseDefinition"),
    ("bd_", "board definition", "recoverBoardDefinition"),
)

_PLAUSIBLE_ID_RE = re.compile(r"^[a-z]+_.+$")


def _detect_recover(asset_id):
    """Return (human_type, mutation) for the dry-run preview."""
    for prefix, human, mutation in sorted(_RECOVER_ROUTES, key=lambda x: -len(x[0])):
        if asset_id.startswith(prefix):
            return human, mutation
    return "unknown (trash fallback)", "recoverDeletedAsset"


@click.command("recover")
@click.argument("asset_id")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report the detected type and target mutation without recovering.",
)
@pass_context
def recover_cmd(ctx, asset_id, dry_run):
    """Recover a soft-deleted asset by ID.

    Trash-fallback recovery (unmapped prefixes like td_) requires OWNER/ADMIN.
    """
    if not _PLAUSIBLE_ID_RE.match(asset_id):
        handle_error(
            ctx,
            CLIError(f"'{asset_id}' is not a recognizable asset id (expected e.g. d_..., i_...)."),
        )
        return

    human, mutation = _detect_recover(asset_id)

    if dry_run:
        # Dry-run makes NO HTTP call; it only reports the routing decision.
        click.echo(f"[dry-run] {asset_id} -> {human} via {mutation}")
        return

    client = make_client(ctx)
    try:
        result = asyncio.run(
            client.request("POST", f"/api/v1/assets/{asset_id}/recover", json={})
        )
    except Exception as e:
        handle_error(ctx, e)
        return

    emit_action_result(ctx, result, label="Recovered")
    if not ctx.json_mode and not getattr(ctx, "quiet_mode", False) and result.get("success"):
        click.echo(f"Read it back with: upscaler get {asset_id}")
