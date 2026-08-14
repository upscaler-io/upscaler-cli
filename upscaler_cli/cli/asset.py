"""Asset management CLI commands."""

import asyncio
import sys
from pathlib import Path

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error


@click.group("asset")
def asset_group():
    """Manage assets: create, update, update-content, delete, set-permissions, add-to-release.

    Examples:
        upscaler asset create --type register_definition --data '{"title": "My Register"}'
        upscaler asset update --asset-id rg_123 --data '{"title": "New Title"}'
        upscaler asset delete --asset-id rg_123 --dry-run
    """
    pass


@asset_group.command("find")
@click.option("--title", default=None, help="Title pattern (supports * and ? wildcards).")
@click.option("--description", default=None, help="Description pattern (* and ? wildcards).")
@click.option("--type", "asset_type", default=None, help="Filter by asset type.")
@click.option("--limit", default=20, help="Max results to return.")
@click.option("--offset", default=0, help="Offset for pagination.")
@pass_context
def asset_find(ctx, title, description, asset_type, limit, offset):
    """Find assets by title and/or description using wildcard matching.

    Supports wildcard patterns: * matches any characters, ? matches single character.
    Without wildcards, performs case-insensitive substring match.

    Examples:
        upscaler asset find --title "Safety*"
        upscaler asset find --title "*procedure*" --type document_definition
        upscaler asset find --description "*compliance*"
        upscaler asset find --title "Risk*" --description "*assessment*"
        upscaler --json asset find --title "*policy*" --limit 50
    """
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json
    from upscaler_cli.formatters.table import format_table

    if not title and not description:
        click.echo("At least one of --title or --description is required.", err=True)
        sys.exit(1)
        return

    client = make_client(ctx)

    params = {"limit": limit, "offset": offset}
    if title:
        params["title"] = title
    if description:
        params["description"] = description
    if asset_type:
        params["type"] = asset_type

    try:
        result = asyncio.run(client.request("GET", "/api/v1/find", params=params))
    except Exception as e:
        handle_error(ctx, e)
        return

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        data = result.get("data", [])
        if not data:
            click.echo("No assets found.")
            return
        metadata = result.get("metadata", {})
        total = metadata.get("total_count", len(data))
        returned = metadata.get("returned_count", len(data))
        if total > returned:
            click.echo(f"Showing {returned} of {total} results (use --offset to paginate)\n")
        click.echo(
            format_table(
                data,
                columns=["asset_id", "title", "asset_type", "description"],
            )
        )


@asset_group.command("create")
@click.option(
    "--type",
    "asset_type",
    required=True,
    type=click.Choice(
        [
            "document_definition",
            "register_definition",
            "record_definition",
            "course_definition",
        ]
    ),
    help="Asset type to create.",
)
@click.option("--data", "data_input", required=True, help="JSON data (value, - for stdin, @file).")
@click.option(
    "--values-type",
    type=click.Choice(["markdown", "slateJson"]),
    default=None,
    help="Content format: 'markdown' or 'slateJson' (default: slateJson).",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@pass_context
def asset_create(ctx, asset_type, data_input, values_type, dry_run):
    """Create a new asset.

    Use --values-type markdown to supply markdown content in the data's 'values' field.

    Examples:
        upscaler asset create --type document_definition \\
            --data '{"title": "My Doc", "values": "# Hello"}' \\
            --values-type markdown
        upscaler asset create --type document_definition --data @doc.json
    """
    from upscaler_cli.cli.helpers import parse_data

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    if values_type:
        data["valuesType"] = values_type

    _execute_asset(ctx, "create", asset_type=asset_type, data=data, dry_run=dry_run)


@asset_group.command("update")
@click.option("--asset-id", required=True, help="Asset ID to update.")
@click.option("--data", "data_input", required=True, help="JSON data.")
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def asset_update(ctx, asset_id, data_input, dry_run):
    """Update asset metadata (title, description, icon)."""
    from upscaler_cli.cli.helpers import parse_data

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    _execute_asset(ctx, "update", asset_id=asset_id, data=data, dry_run=dry_run)


@asset_group.command("update-content")
@click.option("--asset-id", required=True, help="Asset ID to update content for.")
@click.option(
    "--data",
    "data_input",
    required=False,
    default=None,
    help="JSON data with 'values' key. Optional when --file is given.",
)
@click.option(
    "--values-type",
    type=click.Choice(["markdown", "slateJson"]),
    default=None,
    help="Content format: 'markdown' or 'slateJson' (default: slateJson).",
)
@click.option(
    "--file",
    "file_pairs",
    multiple=True,
    help=(
        "FIELD=PATH. Upload PATH to S3 and append to file block "
        "options.name=FIELD on the Slate tree. Repeatable. Validation runs "
        "for ALL files before any upload. Use --content-type to override "
        "the autodetected MIME type for the NEXT --file."
    ),
)
@click.option(
    "--content-type",
    "content_types",
    multiple=True,
    help=(
        "Override autodetected MIME type for the next --file in declaration "
        "order. Pass multiple times to override several files."
    ),
)
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def asset_update_content(
    ctx,
    asset_id,
    data_input,
    values_type,
    file_pairs,
    content_types,
    dry_run,
):
    """Update asset content (Slate JSON or markdown), optionally uploading files.

    For Documents, `--file FIELD=PATH` uploads PATH and appends the file item
    to the matching file block (options.name == FIELD) in the Slate tree.
    Documents accept LWW in v1 (no expectedVersion).

    Examples:
        upscaler asset update-content --asset-id d_123 \\
            --data '{"values": "# Hello"}' --values-type markdown
        upscaler asset update-content --asset-id d_123 --data @content.json
        upscaler asset update-content --asset-id d_abc \\
            --file attachments=./report.pdf --file diagrams=./arch.png
    """
    from upscaler_cli.cli.helpers import parse_data

    data = None
    if data_input:
        try:
            data = parse_data(data_input)
        except Exception as e:
            click.echo(str(e), err=True)
            sys.exit(1)
            return

    if not file_pairs and not data_input:
        click.echo("Either --data or --file is required.", err=True)
        sys.exit(1)
        return

    if values_type:
        data = dict(data or {})
        data["valuesType"] = values_type

    if file_pairs:
        files = _parse_file_pairs(file_pairs, content_types)
        if dry_run:
            _dry_run_asset_with_files(ctx, asset_id, files, data)
            return
        _execute_asset_with_files(ctx, asset_id=asset_id, files=files, data=data)
        return

    _execute_asset(ctx, "update_content", asset_id=asset_id, data=data, dry_run=dry_run)


@asset_group.command("upload-file")
@click.option("--asset-id", required=True, help="Document ID to upload into.")
@click.option(
    "--field",
    "field_name",
    required=True,
    help="File-block name (options.name) on the Slate tree.",
)
@click.option(
    "--path",
    "file_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Local file path to upload.",
)
@click.option(
    "--content-type",
    default=None,
    help="Override autodetected MIME type for this file.",
)
@click.option("--dry-run", is_flag=True, help="Preview without uploading or updating.")
@pass_context
def asset_upload_file(ctx, asset_id, field_name, file_path, content_type, dry_run):
    """Upload one file to a Slate file block on a Document.

    Sugar for: asset update-content --asset-id ASSET --file FIELD=PATH.
    Documents accept LWW in v1 (no expectedVersion).

    Examples:
        upscaler asset upload-file --asset-id d_abc --field attachments \\
            --path ./report.pdf
    """
    files = [
        {"field": field_name, "path": file_path, "content_type": content_type},
    ]
    if dry_run:
        _dry_run_asset_with_files(ctx, asset_id, files, None)
        return
    _execute_asset_with_files(ctx, asset_id=asset_id, files=files, data=None)


def _parse_file_pairs(file_pairs, content_types):
    """Parse --file FIELD=PATH pairs into upload descriptors.

    Content-type overrides are zipped positionally with the file pairs.
    """
    overrides = list(content_types) + [None] * len(file_pairs)
    parsed = []
    for idx, pair in enumerate(file_pairs):
        if "=" not in pair:
            raise click.UsageError(f'--file expects FIELD=PATH, got "{pair}"')
        field, path_str = pair.split("=", 1)
        field = field.strip()
        path_str = path_str.strip()
        if not field or not path_str:
            raise click.UsageError(f'--file expects FIELD=PATH, got "{pair}"')
        path = Path(path_str)
        if not path.exists():
            raise click.UsageError(f"File not found: {path}")
        if not path.is_file():
            raise click.UsageError(f"Not a regular file: {path}")
        parsed.append(
            {"field": field, "path": path, "content_type": overrides[idx]},
        )
    return parsed


@asset_group.command("delete")
@click.option("--asset-id", required=True, help="Asset ID to delete.")
@click.option("--dry-run", is_flag=True, help="Preview without deleting.")
@pass_context
def asset_delete(ctx, asset_id, dry_run):
    """Delete an asset."""
    from upscaler_cli.cli.helpers import confirm_destructive

    if not dry_run and not confirm_destructive("delete", asset_id, ctx.json_mode):
        click.echo("Cancelled.", err=True)
        return

    _execute_asset(ctx, "delete", asset_id=asset_id, dry_run=dry_run)


@asset_group.command("set-permissions")
@click.option("--asset-id", required=True, help="Asset ID.")
@click.option("--data", "data_input", required=True, help="JSON permissions data.")
@pass_context
def asset_set_permissions(ctx, asset_id, data_input):
    """Set permissions on an asset."""
    from upscaler_cli.cli.helpers import parse_data

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    _execute_asset(ctx, "set_permissions", asset_id=asset_id, data=data)


@asset_group.command("add-to-release")
@click.option("--asset-id", required=True, help="Asset ID.")
@click.option("--data", "data_input", required=True, help="JSON release data.")
@pass_context
def asset_add_to_release(ctx, asset_id, data_input):
    """Add an asset to a release."""
    from upscaler_cli.cli.helpers import parse_data

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    _execute_asset(ctx, "add_to_release", asset_id=asset_id, data=data)


@asset_group.command("add-task")
@click.option("--asset-id", required=True, help="Record definition ID (rd_...).")
@click.option("--title", required=True, help="Task title.")
@click.option("--description", default=None, help="Task description (optional).")
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@pass_context
def asset_add_task(ctx, asset_id, title, description, dry_run):
    """Append a new task definition to a record_definition.

    Returns the assigned task definition ID (td_...) which is needed to set
    the task's body via `set-task-values` and gating via `set-task-condition`.

    Example:
        upscaler asset add-task --asset-id rd_abc --title "Meeting Details"
    """
    data = {"title": title}
    if description:
        data["description"] = description

    _execute_asset(
        ctx,
        "add_task_definition",
        asset_id=asset_id,
        data=data,
        dry_run=dry_run,
    )


@asset_group.command("set-task-values")
@click.option("--asset-id", required=True, help="Record definition ID (rd_...).")
@click.option("--task-id", "task_definition_id", required=True, help="Task definition ID (td_...).")
@click.option(
    "--data",
    "data_input",
    default=None,
    help="JSON object with 'values' key. Mutually exclusive with --values-file.",
)
@click.option(
    "--values-file",
    "values_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the body file. With --values-type markdown the file is sent "
         "as a raw string; otherwise it is parsed as a Slate JSON array.",
)
@click.option(
    "--values-type",
    type=click.Choice(["markdown", "slateJson"]),
    default=None,
    help="Content format: 'markdown' or 'slateJson' (default: slateJson).",
)
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def asset_set_task_values(
    ctx,
    asset_id,
    task_definition_id,
    data_input,
    values_file,
    values_type,
    dry_run,
):
    """Set the body of a single task definition (markdown or SlateJS).

    Provide content via either --data (JSON object with 'values') or --values-file
    (raw markdown or Slate JSON file). Pass --values-type markdown for markdown bodies.

    Examples:
        upscaler asset set-task-values --asset-id rd_abc --task-id td_xyz \\
            --values-file task1-body.md --values-type markdown
        upscaler asset set-task-values --asset-id rd_abc --task-id td_xyz \\
            --data '{"values": "## Header\\n..."}' --values-type markdown
    """
    from upscaler_cli.cli.helpers import build_values_payload

    data = build_values_payload(data_input, values_file, values_type)

    data["taskDefinitionId"] = task_definition_id
    if values_type:
        data["valuesType"] = values_type

    _execute_asset(
        ctx,
        "set_task_definition_values",
        asset_id=asset_id,
        data=data,
        dry_run=dry_run,
    )


@asset_group.command("set-task-condition")
@click.option("--asset-id", required=True, help="Record definition ID (rd_...).")
@click.option("--task-id", "task_definition_id", required=True, help="Task definition ID (td_...).")
@click.option(
    "--data",
    "data_input",
    required=True,
    help="JSON with 'condition' AST (see docs).",
)
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def asset_set_task_condition(ctx, asset_id, task_definition_id, data_input, dry_run):
    """Set the gating condition for a single task definition.

    The condition AST controls when the task becomes active. For default
    sequential ordering (task N+1 starts after task N is completed), set:
        {"condition": {"ast": {"operator": "&&", "clauseGroups": {...}}}}

    Example:
        upscaler asset set-task-condition --asset-id rd_abc --task-id td_2 \\
            --data @condition.json
    """
    from upscaler_cli.cli.helpers import parse_data

    try:
        data = parse_data(data_input)
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    if not isinstance(data, dict) or "condition" not in data:
        click.echo("--data must be a JSON object with a 'condition' key.", err=True)
        sys.exit(1)
        return

    data["taskDefinitionId"] = task_definition_id

    _execute_asset(
        ctx,
        "set_task_definition_condition",
        asset_id=asset_id,
        data=data,
        dry_run=dry_run,
    )


@asset_group.command("add-lesson")
@click.option("--asset-id", required=True, help="Course definition ID (cd_...).")
@click.option("--title", required=True, help="Lesson title.")
@click.option("--description", default=None, help="Lesson description (optional).")
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@pass_context
def asset_add_lesson(ctx, asset_id, title, description, dry_run):
    """Append a new lesson definition to a course_definition.

    Returns the assigned lesson definition ID (cl_...) which is needed to set
    the lesson's body via `set-lesson-values`, rename it, or reorder it.

    Example:
        upscaler asset add-lesson --asset-id cd_abc --title "Phishing Basics"
    """
    data = {"title": title}
    if description:
        data["description"] = description

    _execute_asset(
        ctx,
        "add_lesson_definition",
        asset_id=asset_id,
        data=data,
        dry_run=dry_run,
    )


@asset_group.command("set-lesson-title")
@click.option("--asset-id", required=True, help="Course definition ID (cd_...).")
@click.option("--lesson-id", "lesson_definition_id", required=True, help="Lesson ID (cl_...).")
@click.option("--title", required=True, help="New lesson title.")
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def asset_set_lesson_title(ctx, asset_id, lesson_definition_id, title, dry_run):
    """Rename a single lesson definition."""
    _execute_asset(
        ctx,
        "set_lesson_definition_title",
        asset_id=asset_id,
        data={"lessonDefinitionId": lesson_definition_id, "title": title},
        dry_run=dry_run,
    )


@asset_group.command("set-lesson-description")
@click.option("--asset-id", required=True, help="Course definition ID (cd_...).")
@click.option("--lesson-id", "lesson_definition_id", required=True, help="Lesson ID (cl_...).")
@click.option("--description", required=True, help="New lesson description.")
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def asset_set_lesson_description(ctx, asset_id, lesson_definition_id, description, dry_run):
    """Set the description of a single lesson definition."""
    _execute_asset(
        ctx,
        "set_lesson_definition_description",
        asset_id=asset_id,
        data={"lessonDefinitionId": lesson_definition_id, "description": description},
        dry_run=dry_run,
    )


@asset_group.command("set-lesson-values")
@click.option("--asset-id", required=True, help="Course definition ID (cd_...).")
@click.option("--lesson-id", "lesson_definition_id", required=True, help="Lesson ID (cl_...).")
@click.option(
    "--data",
    "data_input",
    default=None,
    help="JSON object with 'values' key. Mutually exclusive with --values-file.",
)
@click.option(
    "--values-file",
    "values_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the body file. With --values-type markdown the file is sent "
         "as a raw string; otherwise it is parsed as a Slate JSON array.",
)
@click.option(
    "--values-type",
    type=click.Choice(["markdown", "slateJson"]),
    default=None,
    help="Content format: 'markdown' or 'slateJson' (default: slateJson).",
)
@click.option("--dry-run", is_flag=True, help="Preview without updating.")
@pass_context
def asset_set_lesson_values(
    ctx,
    asset_id,
    lesson_definition_id,
    data_input,
    values_file,
    values_type,
    dry_run,
):
    """Set the body of a single lesson definition (markdown or SlateJS).

    Provide content via either --data (JSON object with 'values') or --values-file
    (raw markdown or Slate JSON file). Pass --values-type markdown for markdown bodies.

    Examples:
        upscaler asset set-lesson-values --asset-id cd_abc --lesson-id cl_xyz \\
            --values-file lesson1-body.md --values-type markdown
    """
    from upscaler_cli.cli.helpers import build_values_payload

    data = build_values_payload(data_input, values_file, values_type)

    data["lessonDefinitionId"] = lesson_definition_id
    if values_type:
        data["valuesType"] = values_type

    _execute_asset(
        ctx,
        "set_lesson_definition_values",
        asset_id=asset_id,
        data=data,
        dry_run=dry_run,
    )


@asset_group.command("remove-lesson")
@click.option("--asset-id", required=True, help="Course definition ID (cd_...).")
@click.option("--lesson-id", "lesson_definition_id", required=True, help="Lesson ID (cl_...).")
@click.option("--dry-run", is_flag=True, help="Preview without removing.")
@pass_context
def asset_remove_lesson(ctx, asset_id, lesson_definition_id, dry_run):
    """Remove a single lesson definition from a course_definition."""
    _execute_asset(
        ctx,
        "remove_lesson_definition",
        asset_id=asset_id,
        data={"lessonDefinitionId": lesson_definition_id},
        dry_run=dry_run,
    )


@asset_group.command("move-lesson")
@click.option("--asset-id", required=True, help="Course definition ID (cd_...).")
@click.option("--from-id", "from_id", required=True, help="Lesson ID to move (cl_...).")
@click.option("--to-id", "to_id", required=True, help="Target sibling lesson ID (cl_...).")
@click.option("--dry-run", is_flag=True, help="Preview without reordering.")
@pass_context
def asset_move_lesson(ctx, asset_id, from_id, to_id, dry_run):
    """Reorder a lesson definition within a course_definition."""
    _execute_asset(
        ctx,
        "move_lesson_definition",
        asset_id=asset_id,
        data={"fromId": from_id, "toId": to_id},
        dry_run=dry_run,
    )


def _execute_asset(ctx, operation, asset_id=None, asset_type=None, data=None, dry_run=False):
    """Execute an asset operation."""
    from upscaler_cli.cli.helpers import emit_action_result, emit_dry_run, make_client

    payload = {"operation": operation}
    if asset_id:
        payload["asset_id"] = asset_id
    if asset_type:
        payload["asset_type"] = asset_type
    if data:
        payload["data"] = data

    if dry_run:
        emit_dry_run(
            ctx,
            summary=f"would {operation} {asset_type or asset_id or 'asset'}",
            payload=payload,
        )
        return

    client = make_client(ctx)

    try:
        result = asyncio.run(client.request("POST", "/api/v1/assets", json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    emit_action_result(
        ctx, result, label=f"Asset {operation}", id_keys=("assetId", "asset_id", "id")
    )


# File-upload flow for Pattern A (Documents). Documents persist `values` as
# a Slate tree. Resolve the baseline tree, validate every requested FIELD
# against the available file blocks BEFORE any S3 upload, then upload and
# splice each file into the matching block's fileList (idempotent on uid).
# Documents are last-writer-wins on the final update_content call. On
# mid-batch upload failure, best-effort delete the landed uids.


def _execute_asset_with_files(ctx, *, asset_id, files, data):
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.uploads import (
        FieldNotFoundError,
        UploadError,
        append_file_to_slate_block,
        presign_and_upload,
    )

    client = make_client(ctx)
    landed_uids: list[str] = []

    tree = _resolve_baseline_tree(ctx, client, asset_id, data)

    # Validate ALL field names before any upload.
    available_names = _collect_file_block_names(tree)
    for descriptor in files:
        name = descriptor["field"]
        if name not in available_names:
            click.echo(
                f'No file block named "{name}" on document {asset_id}. '
                f"Available file blocks: {', '.join(available_names) or '(none)'}.",
                err=True,
            )
            sys.exit(1)

    # Sequential upload keeps landed_uids ordered for cleanup.
    try:
        for descriptor in files:
            file_bytes = descriptor["path"].read_bytes()
            file_item = asyncio.run(
                presign_and_upload(
                    client,
                    file_name=descriptor["path"].name,
                    content_type=descriptor["content_type"],
                    file_bytes=file_bytes,
                    asset_id=asset_id,
                )
            )
            landed_uids.append(file_item["uid"])
            tree = append_file_to_slate_block(tree, descriptor["field"], file_item)
    except (UploadError, FieldNotFoundError) as e:
        _cleanup_landed_uids(ctx, client, landed_uids)
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    # Documents accept last-writer-wins; no expectedVersion, no retry.
    payload = _build_document_payload(asset_id, tree, data)
    try:
        result = asyncio.run(client.request("POST", "/api/v1/assets", json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    if not result.get("success"):
        click.echo(str(result.get("error") or "Document update failed"), err=True)
        sys.exit(1)
        return

    from upscaler_cli.formatters.json_fmt import format_json as fj

    if ctx.json_mode:
        click.echo(fj(result, compact=True))
    else:
        d = result.get("data", {})
        click.echo(
            f"Asset update-content: {d.get('id', d.get('assetId', asset_id))} "
            f"({len(files)} file(s) uploaded)"
        )


def _resolve_baseline_tree(ctx, client, asset_id, data):
    """Return the Slate tree to splice files into.

    If --data supplies a `values` list, that IS the baseline (no pre-read).
    Otherwise read the current document.
    """
    if data is not None and "values" in data and isinstance(data["values"], list):
        return data["values"]

    try:
        resp = asyncio.run(client.request("GET", f"/api/v1/assets/{asset_id}"))
    except Exception as e:
        handle_error(ctx, e)
        sys.exit(1)
    asset = (resp or {}).get("data") or {}
    values = asset.get("values")
    if not isinstance(values, list):
        click.echo(
            f"Document {asset_id} values are not a Slate tree "
            "(Documents use Pattern A, a list of blocks).",
            err=True,
        )
        sys.exit(1)
    return values


def _collect_file_block_names(tree):
    """Walk the Slate tree and return every file block's options.name."""
    names: list[str] = []
    _walk_for_names(tree, names)
    return names


def _walk_for_names(nodes, out):
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "file":
            name = (node.get("options") or {}).get("name")
            if name:
                out.append(name)
        children = node.get("children")
        if isinstance(children, list):
            _walk_for_names(children, out)


def _build_document_payload(asset_id, tree, data):
    """Compose the POST /api/v1/assets body for an update_content with files."""
    # The spliced Slate tree overrides any `values` from --data; other keys
    # (e.g. valuesType) pass through.
    data_field = dict(data or {})
    data_field["values"] = tree
    return {
        "operation": "update_content",
        "asset_id": asset_id,
        "data": data_field,
    }


def _dry_run_asset_with_files(ctx, asset_id, files, data):
    from upscaler_cli.formatters.json_fmt import format_json

    dry_payload = {
        "operation": "update_content",
        "asset_id": asset_id,
        "files": [{"field": f["field"], "path": str(f["path"])} for f in files],
    }
    if data:
        dry_payload["data"] = data
    if ctx.json_mode:
        click.echo(format_json({"dry_run": True, "payload": dry_payload}, compact=True))
    else:
        click.echo(f"[dry-run] Would upload {len(files)} file(s) and update-content asset:")
        click.echo(format_json(dry_payload))


def _cleanup_landed_uids(ctx, client, uids):
    """Best-effort delete of S3 objects landed before a mid-batch failure.

    5-second timeout per call, single retry. Failures are logged to stderr;
    the S3 lifecycle rule backstops anything we can't delete.
    """
    if not uids:
        return

    import httpx

    for uid in uids:
        ok = False
        for _ in range(2):
            try:
                resp = asyncio.run(
                    asyncio.wait_for(
                        client.request(
                            "POST",
                            "/api/v1/files/delete",
                            json={"uid": uid},
                        ),
                        timeout=5.0,
                    )
                )
                if resp.get("success"):
                    ok = True
                    break
            except (Exception, asyncio.TimeoutError, httpx.HTTPError):
                continue
        if not ok:
            click.echo(
                f"warning: failed to clean up orphan upload uid={uid} "
                f"(S3 lifecycle rule will delete it within 24h)",
                err=True,
            )
