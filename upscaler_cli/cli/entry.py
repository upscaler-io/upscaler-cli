"""Entry management CLI commands (records/items)."""

import asyncio
import sys
from pathlib import Path

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, raise_on_envelope_error

# Cross-package contract emitted by the backend's form-upload block at
# `packages/backend/src/shared/service/asset/blocks/form-upload.js`.
# Locked by tests on both sides; do not change without re-syncing both.
AGENT_SCHEMA_FILE_UPLOAD_TYPE = "file_upload"
# Form-tables become `type: "table"` with a `columns[]` array in the agent
# schema (built by `form-table.js::toAgentSchema`). Each column is itself an
# agent-schema descriptor, so a file-upload column has type "file_upload".
AGENT_SCHEMA_TABLE_TYPE = "table"


@click.group("entry")
def entry_group():
    """Manage record/item entries: create, update, save-draft, delete.

    Task completion is human-only: the old task-completion command was
    removed. Use save-draft to stage values with a required note; the
    assignee reviews and finalizes the task in the app.

    Examples:
        upscaler entry create --definition-id rg_123 --data '{"title": "New item"}'
        upscaler entry update --entry-id i_456 --data '{"values": {"status": "done"}}'
        upscaler entry save-draft --task-id t_789 --note "Prefilled from Q2 report"
        upscaler entry create --definition-id rg_123 --data @payload.json --dry-run
    """
    pass


@entry_group.command("create")
@click.option(
    "--definition-id",
    required=True,
    help="Definition ID (rd_ = record, rg_ = register).",
)
@click.option("--data", "data_input", required=True, help="JSON data (value, - for stdin, @file).")
@click.option(
    "--note",
    default=None,
    help="Optional note for the human reviewer, stored with the draft.",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@pass_context
def entry_create(ctx, definition_id, data_input, note, dry_run):
    """Create a new entry.

    Entries created here land as drafts for human review; the
    reviewer finalizes them in the app. Use --note to tell the
    reviewer what was prepared.
    """
    from upscaler_cli.cli.helpers import parse_data, validate_entry_data

    try:
        data = validate_entry_data(parse_data(data_input))
    except Exception as e:
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    _execute_entry(
        ctx, "create", definition_id=definition_id, note=note, data=data, dry_run=dry_run
    )


@entry_group.command("update")
@click.option("--entry-id", required=True, help="Entry ID to update.")
@click.option(
    "--data",
    "data_input",
    required=False,
    default=None,
    help="JSON data. Optional when --file is given.",
)
@click.option(
    "--file",
    "file_pairs",
    multiple=True,
    help=(
        "FIELD=PATH. Upload PATH to S3 and append to file field FIELD. "
        "Repeatable. Each path is read once and uploaded before any "
        "mutation is sent (no partial state). Use --content-type to "
        "override the autodetected MIME type for the NEXT --file."
    ),
)
@click.option(
    "--task-id",
    default=None,
    help=(
        "When set, save the values as a task draft (saveTaskDraft) instead "
        "of mergeItemValues. The draft awaits human review; the assignee "
        "completes the task in the app."
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
@click.option(
    "--note",
    default=None,
    help="Optional note for the human reviewer, stored with the pending revision.",
)
@click.option("--dry-run", is_flag=True, help="Preview without uploading or updating.")
@pass_context
def entry_update(ctx, entry_id, data_input, file_pairs, task_id, content_types, note, dry_run):
    """Update an existing entry, optionally uploading files.

    Updates land as pending revisions for human review; the
    reviewer finalizes them in the app. Use --note to tell the
    reviewer what changed.
    """
    from upscaler_cli.cli.helpers import parse_data, validate_entry_data

    data = None
    if data_input:
        try:
            data = validate_entry_data(parse_data(data_input))
        except Exception as e:
            click.echo(str(e), err=True)
            sys.exit(1)
            return

    if not file_pairs and not data_input:
        click.echo("Either --data or --file is required.", err=True)
        sys.exit(1)
        return

    files = _parse_file_pairs(file_pairs, content_types) if file_pairs else []

    _execute_entry(
        ctx,
        "update",
        entry_id=entry_id,
        task_id=task_id,
        note=note,
        data=data,
        files=files,
        dry_run=dry_run,
    )


@entry_group.command("upload-file")
@click.option("--entry-id", required=True, help="Entry ID to upload into.")
@click.option("--field", "field_name", required=True, help="File-field name (options.name).")
@click.option(
    "--path",
    "file_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Local file path to upload.",
)
@click.option(
    "--task-id",
    default=None,
    help=(
        "When set, save as a task draft for human review "
        "(saveTaskDraft) instead of mergeItemValues."
    ),
)
@click.option(
    "--content-type",
    default=None,
    help="Override autodetected MIME type for this file.",
)
@click.option("--dry-run", is_flag=True, help="Preview without uploading or updating.")
@pass_context
def entry_upload_file(ctx, entry_id, field_name, file_path, task_id, content_type, dry_run):
    """Upload one file to a file field on an entry.

    Sugar for: entry update --entry-id ENTRY --file FIELD=PATH [--task-id ID].

    Examples:
        upscaler entry upload-file --entry-id i_123 --field evidence --path ./report.pdf
        upscaler entry upload-file --entry-id r_789 --task-id t_321 \\
            --field supporting_documents --path ./audit.pdf
    """
    files = [
        {
            "field": field_name,
            "path": file_path,
            "content_type": content_type,
        }
    ]
    _execute_entry(
        ctx,
        "update",
        entry_id=entry_id,
        task_id=task_id,
        data=None,
        files=files,
        dry_run=dry_run,
    )


def _parse_file_pairs(file_pairs, content_types):
    """Parse repeated --file FIELD=PATH pairs into upload descriptors.

    Content-type overrides zip positionally: the Nth --content-type applies
    to the Nth --file. Extra overrides are ignored.
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
        parsed.append({"field": field, "path": path, "content_type": overrides[idx]})
    return parsed


@entry_group.command("save-draft")
@click.option("--entry-id", default=None, help="Record ID (auto-detected from task if omitted).")
@click.option("--task-id", required=True, help="Task ID to save the draft on.")
@click.option("--note", required=True, help="Note for the human reviewer (what was prepared).")
@click.option("--data", "data_input", default=None, help="Optional JSON data.")
@click.option("--dry-run", is_flag=True, help="Preview task fields without saving.")
@pass_context
def entry_save_draft(ctx, entry_id, task_id, note, data_input, dry_run):
    """Save a draft on a task for human review.

    Stages the provided values plus a required --note on the task;
    the assignee reviews and finalizes the task in the app. Agents
    never complete tasks directly.

    Use --dry-run to see the task's form fields before saving.
    The --entry-id is auto-detected from the task if not provided.

    Examples:
        upscaler entry save-draft --task-id t_xyz --note "Prefilled" --dry-run
        upscaler entry save-draft --task-id t_xyz --note "Prefilled" --data '{"values": {...}}'
        upscaler entry save-draft --entry-id r_abc --task-id t_xyz \\
            --note "Prefilled" --data '{"values": {...}}'
    """
    from upscaler_cli.cli.helpers import parse_data, validate_entry_data

    data = None
    if data_input:
        try:
            data = validate_entry_data(parse_data(data_input))
        except Exception as e:
            click.echo(str(e), err=True)
            sys.exit(1)
            return

    _execute_entry(
        ctx,
        "save_task_draft",
        entry_id=entry_id,
        task_id=task_id,
        note=note,
        data=data,
        dry_run=dry_run,
    )


@entry_group.command("delete")
@click.option("--entry-id", required=True, help="Entry ID to delete.")
@click.option("--dry-run", is_flag=True, help="Preview without deleting.")
@pass_context
def entry_delete(ctx, entry_id, dry_run):
    """Delete an entry."""
    from upscaler_cli.cli.helpers import confirm_destructive

    if not dry_run and not confirm_destructive("delete", entry_id, ctx.json_mode):
        click.echo("Cancelled.", err=True)
        return

    _execute_entry(ctx, "delete", entry_id=entry_id, dry_run=dry_run)


def _execute_entry(
    ctx,
    operation,
    definition_id=None,
    entry_id=None,
    task_id=None,
    note=None,
    data=None,
    dry_run=False,
    files=None,
):
    """Execute an entry operation."""
    from upscaler_cli.cli.helpers import emit_action_result, make_client
    from upscaler_cli.formatters.json_fmt import format_json

    payload = {"operation": operation}
    if definition_id:
        payload["definition_id"] = definition_id
    if entry_id:
        payload["entry_id"] = entry_id
    if task_id:
        payload["task_id"] = task_id
    # --note travels inside the data object: /api/v1/entries accepts the
    # reviewer note only as data.note. An explicit note in --data wins.
    if note:
        data = dict(data or {})
        data.setdefault("note", note)
    if data:
        payload["data"] = data

    if files:
        # File-upload flow: read current entry values, validate every named
        # file field, upload all files, splice items into the values tree,
        # then issue ONE mutation. The no-files path below stays unchanged.
        if dry_run:
            dry_payload = dict(payload)
            dry_payload["files"] = [{"field": f["field"], "path": str(f["path"])} for f in files]
            if ctx.quiet_mode:
                click.echo(f"[dry-run] would upload {len(files)} file(s) and {operation} entry")
            elif ctx.json_mode:
                click.echo(format_json({"dry_run": True, "payload": dry_payload}, compact=True))
            else:
                click.echo(f"[dry-run] Would upload {len(files)} file(s) and {operation} entry:")
                click.echo(format_json(dry_payload))
            return
        _execute_entry_with_files(
            ctx,
            entry_id=entry_id,
            task_id=task_id,
            data=data,
            files=files,
        )
        return

    if dry_run:
        if ctx.quiet_mode:
            click.echo(f"[dry-run] would {operation} entry")
            return
        dry_run_data = {"dry_run": True, "payload": payload}

        # For save_task_draft, fetch and show the task's form fields
        if operation == "save_task_draft" and task_id:
            try:
                client = make_client(ctx)
                task_result = asyncio.run(client.request("GET", f"/api/v1/tasks/{task_id}"))
                task_data = task_result.get("data", {})
                definition = task_data.get("definition", [])
                fields = []
                if isinstance(definition, list):
                    for block in definition:
                        if block.get("type", "").startswith("form-"):
                            opts = block.get("options", {})
                            if opts.get("name"):
                                fields.append(
                                    {
                                        "key": opts["name"],
                                        "label": opts.get("title", opts["name"]),
                                        "type": block["type"],
                                        "required": opts.get("required", False),
                                    }
                                )
                if fields:
                    dry_run_data["task_fields"] = fields
                current_values = task_data.get("values", {})
                if current_values:
                    dry_run_data["current_values"] = current_values
            except Exception:
                pass  # Non-critical — still show the dry-run payload

        if ctx.json_mode:
            click.echo(format_json(dry_run_data, compact=True))
        else:
            click.echo(f"[dry-run] Would {operation} entry:")
            click.echo(format_json(dry_run_data))
        return

    client = make_client(ctx)

    try:
        result = asyncio.run(client.request("POST", "/api/v1/entries", json=payload))
    except Exception as e:
        handle_error(ctx, e)
        return

    # After record creation, enrich tasks with their form field definitions.
    # Skipped in --quiet mode: the enrichment makes extra calls and only
    # populates output that quiet mode discards anyway.
    if not ctx.quiet_mode and operation == "create" and result.get("data", {}).get("tasks"):
        try:
            for task in result["data"]["tasks"]:
                task_detail = asyncio.run(client.request("GET", f"/api/v1/tasks/{task['id']}"))
                task_def = task_detail.get("data", {}).get("definition", [])
                if isinstance(task_def, list):
                    fields = []
                    for block in task_def:
                        if block.get("type", "").startswith("form-"):
                            opts = block.get("options", {})
                            if opts.get("name"):
                                fields.append(
                                    {
                                        "key": opts["name"],
                                        "label": opts.get("title", opts["name"]),
                                        "type": block["type"],
                                        "required": opts.get("required", False),
                                    }
                                )
                    if fields:
                        task["fields"] = fields
        except Exception:
            pass  # Non-critical enrichment

    emit_action_result(ctx, result, label=f"Entry {operation}", id_keys=("id", "entryId"))


# File-upload flow for Pattern B (Items + Records, which persist `values`
# as a flat dict keyed by ff_*). Fetch the agent schema, resolve --field
# <title> to ff_*, fail loud BEFORE any S3 upload on unknown/ambiguous/
# non-file fields, read current values + version, upload + splice, then send
# ONE mutation. On ITEM_VERSION_CONFLICT (items only) re-read, re-append,
# and retry; task drafts (saveTaskDraft) retain last-writer-wins. On mid-batch upload
# failure, best-effort delete the landed uids.


_CONFLICT_RETRY_BUDGET = 3


def _execute_entry_with_files(ctx, *, entry_id, task_id, data, files):
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.uploads import UploadError, presign_and_upload

    client = make_client(ctx)
    landed_uids: list[str] = []

    # Records hold their file fields on individual tasks, so an upload must name
    # the task: it drives both the schema lookup and the values read/merge.
    if _is_record_id(entry_id) and not task_id:
        click.echo(
            "Record file uploads require --task-id (records hold fields on tasks).",
            err=True,
        )
        sys.exit(1)

    schema_fields = _fetch_schema_or_die(ctx, client, entry_id, task_id=task_id)

    # Hard-fail before any S3 upload on unknown/ambiguous/non-file fields.
    resolved = _resolve_field_descriptors(ctx, schema_fields, files)

    values, expected_version = _fetch_entry_values(ctx, client, entry_id, task_id=task_id)

    # The splice spec is built once during upload and re-applied on
    # every conflict retry. Top-level entries land via append_file_to_form_field
    # (uid-idempotent). Nested entries are grouped by table_key so all files
    # destined for a given table land in a single new row.
    splice_spec: dict[str, list] = {
        "top_level": [],
        "nested": {},
    }
    try:
        for descriptor in resolved:
            file_bytes = descriptor["path"].read_bytes()
            file_item = asyncio.run(
                presign_and_upload(
                    client,
                    file_name=descriptor["path"].name,
                    content_type=descriptor["content_type"],
                    file_bytes=file_bytes,
                    asset_id=entry_id,
                )
            )
            landed_uids.append(file_item["uid"])

            if "table_key" in descriptor:
                table_rows = splice_spec["nested"].setdefault(descriptor["table_key"], {})
                table_rows.setdefault(descriptor["col_key"], []).append(file_item)
            else:
                splice_spec["top_level"].append((descriptor["ff_key"], file_item))
    except UploadError as e:
        _cleanup_landed_uids(ctx, client, landed_uids)
        click.echo(str(e), err=True)
        sys.exit(1)
        return

    values = _apply_splice_spec(values, splice_spec)

    result = _submit_with_retry(
        ctx,
        client,
        entry_id=entry_id,
        task_id=task_id,
        values=values,
        expected_version=expected_version,
        data=data,
        splice_spec=splice_spec,
        landed_uids=landed_uids,
    )

    if result is None:
        return

    from upscaler_cli.formatters.json_fmt import format_json as fj

    if ctx.json_mode:
        click.echo(fj(result, compact=True))
    else:
        d = result.get("data", {})
        click.echo(
            f"Entry update: {d.get('id', d.get('entryId', entry_id))} "
            f"({len(landed_uids)} file(s) uploaded)"
        )


def _apply_splice_spec(values, splice_spec):
    """Apply the upload-time splice spec to ``values``.

    Top-level appends are uid-idempotent (handled inside
    ``append_file_to_form_field``). Nested table rows are uid-idempotent at
    the row level via ``append_row_to_table_field``: a freshly-read values
    dict will not contain the row, so the retry path simply re-appends.
    """
    from upscaler_cli.uploads import append_file_to_form_field, append_row_to_table_field

    for ff_key, file_item in splice_spec["top_level"]:
        values = append_file_to_form_field(values, ff_key, file_item)
    for table_key, row in splice_spec["nested"].items():
        values = append_row_to_table_field(values, table_key, row)
    return values


def _is_record_id(entry_id):
    return bool(entry_id) and (entry_id.startswith("r_") or entry_id.startswith("rec_"))


def _fetch_schema_or_die(ctx, client, entry_id, task_id=None):
    path = f"/api/v1/assets/{entry_id}/schema"
    if task_id and _is_record_id(entry_id):
        # Records carry fields per-task; name the task so the backend returns
        # that task's field schema instead of a (non-existent) record schema.
        # Gate on record-ness to match `_fetch_entry_values`: items keep their
        # own values source even with a --task-id, so scoping the schema to a
        # task there would diverge schema from values.
        path += f"?taskId={task_id}"
    try:
        resp = asyncio.run(client.request("GET", path))
    except Exception as e:
        handle_error(ctx, e)
        sys.exit(1)
    if not resp.get("success"):
        click.echo(
            f"Failed to fetch schema for {entry_id}: {resp.get('error') or 'unknown error'}",
            err=True,
        )
        sys.exit(1)
    return (resp.get("data") or {}).get("fields") or []


def _resolve_field_descriptors(ctx, schema_fields, files):
    """Resolve each --file descriptor to either a top-level file field or a
    file column nested inside a form-table.

    Top-level form (existing): ``--file "Evidence=path"`` or
    ``--file "ff_a=path"`` resolves against top-level fields with
    ``type == "file_upload"``.

    Dotted form (new): ``--file "Table.Column=path"`` or
    ``--file "ff_table.ff_col=path"`` resolves ``Table`` against top-level
    fields with ``type == "table"``, then ``Column`` against that table's
    ``columns[]`` entries with ``type == "file_upload"``.

    All resolution failures (unknown table, unknown column, ambiguous label,
    non-file target) raise SystemExit before any S3 traffic.
    """
    top_file_fields = [f for f in schema_fields if f.get("type") == AGENT_SCHEMA_FILE_UPLOAD_TYPE]
    table_fields = [f for f in schema_fields if f.get("type") == AGENT_SCHEMA_TABLE_TYPE]
    by_key = {f["key"]: f for f in schema_fields if f.get("key")}
    titles_to_keys: dict[str, list[str]] = {}
    for f in top_file_fields:
        norm = (f.get("label") or "").strip().lower()
        if norm:
            titles_to_keys.setdefault(norm, []).append(f["key"])

    resolved = []
    for descriptor in files:
        raw = descriptor["field"]
        raw_stripped = raw.strip()

        # Dotted form: TableLabel.ColumnLabel or ff_table.ff_col. The split
        # is unambiguous because top-level ff_* keys never contain dots.
        if "." in raw_stripped:
            resolved.append(_resolve_nested(ctx, descriptor, raw_stripped, table_fields))
            continue

        # Exact ff_* match, case-sensitive.
        if raw_stripped in by_key:
            target = by_key[raw_stripped]
            if target.get("type") != AGENT_SCHEMA_FILE_UPLOAD_TYPE:
                _fail_loud_non_file(ctx, raw_stripped, top_file_fields, table_fields)
            resolved.append({**descriptor, "ff_key": raw_stripped})
            continue

        # Title match, case-insensitive trimmed.
        norm = raw_stripped.lower()
        candidates = titles_to_keys.get(norm, [])
        if len(candidates) == 1:
            resolved.append({**descriptor, "ff_key": candidates[0]})
            continue
        if len(candidates) > 1:
            click.echo(
                f'Title "{raw_stripped}" matches multiple fields: '
                f'{", ".join(candidates)}. Pass --field <ff_id> to disambiguate.',
                err=True,
            )
            sys.exit(1)
        _fail_loud_unknown(ctx, raw_stripped, top_file_fields, table_fields)
    return resolved


def _bare_col_key(col_key):
    """Reduce a possibly-dotted form-table column key to its bare column id.

    The backend schema endpoint surfaces a table column's key as the dotted
    composite ``ff_table.ff_col`` (the flattened form-field key), with a null
    ``dataIndex``. The persisted row and every UI renderer, however, key the
    cell by the BARE column id ``ff_col`` (``column.dataIndex``/``column.key``),
    and the store writes values verbatim. Splicing under the dotted key
    therefore produces a row that persists but never renders. We always reduce
    to the bare last segment. Field ids never contain a literal dot, so the last
    dot-segment is the column's own id; idempotent for already-bare keys. See B9
    in the agent-skills alignment proposal for the upstream schema fix.
    """
    return col_key.rsplit(".", 1)[-1] if col_key else col_key


def _resolve_nested(ctx, descriptor, raw_stripped, table_fields):
    """Resolve `Table.Column` into a {table_key, col_key} descriptor.

    ``col_key`` is always returned BARE (see ``_bare_col_key``) so the splice
    writes the row shape the store and UI expect, regardless of whether the
    schema reported the column key as bare or dotted.
    """
    table_raw, col_raw = (part.strip() for part in raw_stripped.split(".", 1))
    if not table_raw or not col_raw:
        click.echo(
            f'--file FIELD "{raw_stripped}" is not a valid TABLE.COLUMN path.',
            err=True,
        )
        sys.exit(1)

    table = _match_table(table_raw, table_fields)
    if table is None:
        _fail_loud_unknown_table(ctx, table_raw, table_fields)

    columns = [c for c in (table.get("columns") or []) if isinstance(c, dict)]
    file_columns = [c for c in columns if c.get("type") == AGENT_SCHEMA_FILE_UPLOAD_TYPE]

    # Match the column by its full schema key OR its bare last segment: the
    # backend reports table columns as the dotted `ff_table.ff_col`, but a user
    # (or the skill) may pass either the dotted path or the bare `ff_col`.
    col_by_key = {}
    for c in columns:
        k = c.get("key")
        if not k:
            continue
        col_by_key.setdefault(k, c)
        col_by_key.setdefault(_bare_col_key(k), c)

    if col_raw in col_by_key:
        col = col_by_key[col_raw]
        if col.get("type") != AGENT_SCHEMA_FILE_UPLOAD_TYPE:
            _fail_loud_non_file_column(ctx, table, _bare_col_key(col.get("key")), file_columns)
        return {
            **descriptor,
            "table_key": table["key"],
            "col_key": _bare_col_key(col["key"]),
        }

    norm = col_raw.lower()
    candidates = [
        c["key"]
        for c in file_columns
        if (c.get("label") or "").strip().lower() == norm and c.get("key")
    ]
    if len(candidates) == 1:
        return {
            **descriptor,
            "table_key": table["key"],
            "col_key": _bare_col_key(candidates[0]),
        }
    if len(candidates) > 1:
        click.echo(
            f'Column "{col_raw}" in table "{table.get("label") or table["key"]}" '
            f"matches multiple file columns: "
            f'{", ".join(_bare_col_key(k) for k in candidates)}. '
            f"Pass the ff_* key to disambiguate.",
            err=True,
        )
        sys.exit(1)
    _fail_loud_unknown_column(ctx, table, col_raw, file_columns)


def _match_table(table_raw, table_fields):
    by_key = {t["key"]: t for t in table_fields if t.get("key")}
    if table_raw in by_key:
        return by_key[table_raw]
    norm = table_raw.lower()
    label_matches = [t for t in table_fields if (t.get("label") or "").strip().lower() == norm]
    if len(label_matches) == 1:
        return label_matches[0]
    # Ambiguous tables (two with the same label) fall through to the
    # unknown-table error so the user is told to pass the ff_* key.
    return None


def _fail_loud_unknown(ctx, field_name, file_fields, table_fields=()):
    available = ", ".join(f'"{f.get("label")}" → {f.get("key")}' for f in file_fields) or "(none)"
    extra = ""
    if table_fields:
        nested = []
        for t in table_fields:
            for c in t.get("columns") or []:
                if isinstance(c, dict) and c.get("type") == AGENT_SCHEMA_FILE_UPLOAD_TYPE:
                    nested.append(
                        f'"{t.get("label") or t.get("key")}.'
                        f'{c.get("label") or _bare_col_key(c.get("key"))}" → '
                        f'{t.get("key")}.{_bare_col_key(c.get("key"))}'
                    )
        if nested:
            extra = f" Nested file columns (use TABLE.COLUMN form): {', '.join(nested)}."
    click.echo(
        f'No file field named "{field_name}" on this entry. '
        f"Available file fields (title → id): {available}.{extra}",
        err=True,
    )
    sys.exit(1)


def _fail_loud_non_file(ctx, key, file_fields, table_fields=()):
    available = ", ".join(f.get("key") for f in file_fields) or "(none)"
    extra = ""
    if table_fields and key in {t.get("key") for t in table_fields}:
        extra = (
            " (matched table; specify a column with TABLE.COLUMN to upload "
            "into a nested file column)"
        )
    click.echo(
        f'Field "{key}" is not a file-upload field{extra}. ' f"Available file fields: {available}.",
        err=True,
    )
    sys.exit(1)


def _fail_loud_unknown_table(ctx, table_raw, table_fields):
    available = ", ".join(f'"{t.get("label")}" → {t.get("key")}' for t in table_fields) or "(none)"
    click.echo(
        f'No table field named "{table_raw}" on this entry. '
        f"Available tables (title → id): {available}.",
        err=True,
    )
    sys.exit(1)


def _fail_loud_unknown_column(ctx, table, col_raw, file_columns):
    available = (
        ", ".join(f'"{c.get("label")}" → {_bare_col_key(c.get("key"))}' for c in file_columns)
        or "(none)"
    )
    click.echo(
        f'No file column "{col_raw}" in table '
        f'"{table.get("label") or table.get("key")}". '
        f"Available file columns (title → id): {available}.",
        err=True,
    )
    sys.exit(1)


def _fail_loud_non_file_column(ctx, table, col_key, file_columns):
    available = ", ".join(_bare_col_key(c.get("key")) for c in file_columns) or "(none)"
    click.echo(
        f'Column "{col_key}" in table '
        f'"{table.get("label") or table.get("key")}" is not a file-upload column. '
        f"Available file columns: {available}.",
        err=True,
    )
    sys.exit(1)


def _fetch_entry_values(ctx, client, entry_id, task_id=None):
    # A record's values live on its tasks, not at the record level, so a file
    # upload to a record reads (and later merges into) the named task's values.
    # saveTaskDraft is last-writer-wins, so no version is needed for records.
    if _is_record_id(entry_id) and task_id:
        try:
            task = asyncio.run(client.request("GET", f"/api/v1/tasks/{task_id}"))
        except Exception as e:
            handle_error(ctx, e)
            sys.exit(1)
        # A 200 may still carry {"success": false, "data": null}; fail loud
        # rather than collapsing to empty values and uploading anyway.
        raise_on_envelope_error(ctx, task)
        task_data = (task or {}).get("data") or {}
        values = task_data.get("values") if isinstance(task_data, dict) else None
        if values is None:
            values = {}
        if not isinstance(values, dict):
            click.echo("Task values are not a flat dict.", err=True)
            sys.exit(1)
        return values, None
    try:
        entry = asyncio.run(client.request("GET", f"/api/v1/assets/{entry_id}"))
    except Exception as e:
        handle_error(ctx, e)
        sys.exit(1)
    raise_on_envelope_error(ctx, entry)
    asset = (entry or {}).get("data") or {}
    values = asset.get("values") if isinstance(asset, dict) else None
    if values is None:
        values = {}
    if not isinstance(values, dict):
        click.echo(
            "Entry values are not a flat dict (Items + Records use Pattern B).",
            err=True,
        )
        sys.exit(1)
    return values, asset.get("version")


def _submit_with_retry(
    ctx,
    client,
    *,
    entry_id,
    task_id,
    values,
    expected_version,
    data,
    splice_spec,
    landed_uids,
):
    attempt = 0
    current_values = values
    current_version = expected_version

    while attempt < _CONFLICT_RETRY_BUDGET:
        attempt += 1
        payload = _build_entry_mutation_payload(
            entry_id=entry_id,
            task_id=task_id,
            values=current_values,
            data=data,
            expected_version=current_version if not task_id else None,
        )
        try:
            result = asyncio.run(client.request("POST", "/api/v1/entries", json=payload))
        except Exception as e:
            if _is_version_conflict(e) and not task_id and attempt < _CONFLICT_RETRY_BUDGET:
                current_values, current_version = _refresh_and_reapply(
                    ctx, client, entry_id, splice_spec
                )
                continue
            handle_error(ctx, e)
            return None

        if not result.get("success"):
            err = result.get("error") or ""
            if "ITEM_VERSION_CONFLICT" in err and not task_id:
                if attempt >= _CONFLICT_RETRY_BUDGET:
                    _emit_retry_exhausted(ctx, landed_uids)
                    return None
                current_values, current_version = _refresh_and_reapply(
                    ctx, client, entry_id, splice_spec
                )
                continue
            click.echo(str(err), err=True)
            sys.exit(1)
            return None

        return result

    _emit_retry_exhausted(ctx, landed_uids)
    return None


def _refresh_and_reapply(ctx, client, entry_id, splice_spec):
    """Re-read the entry and re-apply the splice spec.

    Returns (next_values, next_version). Top-level appends dedupe on uid;
    nested rows are appended unconditionally because the failed PATCH never
    landed our row on the server (uid match against existing rows acts as
    a belt-and-braces idempotency check).
    """
    try:
        refreshed = asyncio.run(client.request("GET", f"/api/v1/assets/{entry_id}"))
    except Exception as e:
        handle_error(ctx, e)
        sys.exit(1)
    asset = (refreshed or {}).get("data") or {}
    next_values = asset.get("values")
    if next_values is None:
        next_values = {}
    if not isinstance(next_values, dict):
        click.echo("Entry values not a flat dict after conflict-refresh.", err=True)
        sys.exit(1)
    next_values = _apply_splice_spec(next_values, splice_spec)
    return next_values, asset.get("version")


def _build_entry_mutation_payload(*, entry_id, task_id, values, data, expected_version):
    """Compose the POST /api/v1/entries body for a Pattern B update with files.

    `data.values` is the file-spliced flat dict the backend merges into the
    Item aggregate. `--data` overrides layer onto the same dict so one
    mutation carries both file appends and any text-field updates; the
    reviewer note (already folded into `data` by `_execute_entry`) is carried
    as `data.note`. `expectedVersion` is omitted when task_id is set
    (saveTaskDraft is LWW).
    """
    payload = {"operation": "update", "entry_id": entry_id}
    if task_id:
        payload["task_id"] = task_id

    spliced = dict(values)
    if data and isinstance(data.get("values"), dict):
        spliced.update(data["values"])

    data_field: dict = {"values": spliced}
    if data and data.get("note"):
        data_field["note"] = data["note"]
    if expected_version is not None:
        data_field["expectedVersion"] = expected_version
    payload["data"] = data_field
    return payload


def _is_version_conflict(exception):
    msg = str(exception) if exception else ""
    return "ITEM_VERSION_CONFLICT" in msg


def _cleanup_landed_uids(ctx, client, uids):
    """Best-effort delete of S3 objects landed before a mid-batch failure.

    Short timeout + single retry per call. Failures are logged to stderr;
    the S3 lifecycle rule backstops anything we can't delete (~24h via the
    `lifecycle=pending` tag).
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


def _emit_retry_exhausted(ctx, landed_uids):
    import json

    err_body = {
        "error": "ITEM_VERSION_CONFLICT",
        "message": (
            "mergeItemValues conflict-retry budget exhausted "
            f"({_CONFLICT_RETRY_BUDGET} attempts)."
        ),
        "orphan_uids": landed_uids,
    }
    if ctx.json_mode:
        click.echo(json.dumps(err_body), err=True)
    else:
        click.echo(err_body["message"], err=True)
        if landed_uids:
            click.echo("Files uploaded to S3 (subject to lifecycle cleanup):", err=True)
            for uid in landed_uids:
                click.echo(f"  {uid}", err=True)
    sys.exit(1)
