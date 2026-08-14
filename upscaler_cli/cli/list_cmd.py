"""List command for definitions, entries, todos, field options."""

import asyncio
import json
import re

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, raise_on_envelope_error

# Top-level filter keys that are not asset value fields. Anything else passed
# via --filter without a `values.` prefix gets auto-prefixed for ergonomics.
_SYSTEM_FIELDS = {
    "status",
    "title",
    "description",
    "tags",
    "archived",
    "dueAt",
    "createdAt",
    "updatedAt",
    "createdBy",
    "updatedBy",
    "participants",
    "assetType",
    "completedAt",
    "completedBy",
}

_FIELD_KEY_RE = re.compile(r"^ff_[A-Za-z0-9_]+$")


def _parse_filter_pair(raw):
    """Parse a single --filter argument of shape 'key=value'.

    Returns (key, value). Comma-separated values produce a list. Leaves
    type coercion to JSON parsing if the value looks like JSON (e.g. starts
    with `[`, `{`, a digit, or is one of true/false/null). Otherwise treated
    as a plain string.

    Auto-prefixes `key` with `values.` when key is not a known system field
    and does not already start with `values.`. This matches how users think
    about filters ("severity" really means "values.severity") and keeps the
    CLI compatible with backend allowlist conventions.
    """
    if "=" not in raw:
        raise click.BadParameter(
            f"--filter expects 'key=value' (got: {raw!r})"
        )
    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        raise click.BadParameter("--filter key cannot be empty")

    if "." not in key and key not in _SYSTEM_FIELDS:
        key = f"values.{key}"

    if "," in value and not (value.startswith("[") or value.startswith("{")):
        parsed = [_coerce_scalar(v.strip()) for v in value.split(",") if v.strip()]
    elif value.startswith(("[", "{")) or value in ("true", "false", "null") or (
        value and (value[0].isdigit() or value[0] == "-")
    ):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
    else:
        parsed = value

    return key, parsed


def _coerce_scalar(v):
    """Coerce a comma-list element. Numbers/bools/null parsed; rest stays str."""
    if v in ("true", "false", "null"):
        return json.loads(v)
    try:
        return json.loads(v)
    except (json.JSONDecodeError, ValueError):
        return v


def _parse_sort(raw):
    """Parse 'field:asc' or 'field:desc' into {dataIndex, order}."""
    if not raw:
        return None
    if ":" in raw:
        field, order = raw.split(":", 1)
    else:
        field, order = raw, "asc"
    field = field.strip()
    order_map = {"asc": "ascend", "ascend": "ascend", "desc": "descend", "descend": "descend"}
    if order.strip() not in order_map:
        raise click.BadParameter(
            f"--sort order must be asc|desc (got: {order!r})"
        )
    return {"dataIndex": field, "order": order_map[order.strip()]}


@click.group("list")
def list_group():
    """List definitions, entries, todos, or field options.

    Examples:
        upscaler list definitions
        upscaler list entries --definition-id rg_123
        upscaler list entries --definition-id rg_123 --filter status=open
        upscaler list entries --definition-id rg_123 \\
            --filter values.severity=high,medium --sort updatedAt:desc
        upscaler --json list todos
        upscaler list field-options --definition-id rg_123 --field-key status
    """
    pass


@list_group.command("definitions")
@click.option("--limit", default=20, type=int, help="Max results to return (1-200).")
@click.option("--offset", default=0, type=int, help="Offset for pagination.")
@pass_context
def list_definitions(ctx, limit, offset):
    """List all definitions (registers, records).

    Results are paginated; use --limit/--offset to page through, matching
    `list entries`.
    """
    _do_list(ctx, type_name="definitions", limit=limit, offset=offset)


@list_group.command("entries")
@click.option("--definition-id", required=True, help="Definition ID to list entries for.")
@click.option(
    "--filter",
    "filters_raw",
    multiple=True,
    help=(
        "Filter entries by field value, e.g. --filter values.status=open. "
        "Keys without a `.` are auto-prefixed with `values.`. Pass multiple "
        "times for an AND. Comma-separated values produce an OR list."
    ),
)
@click.option(
    "--sort",
    "sort_raw",
    default=None,
    help="Sort entries, e.g. --sort updatedAt:desc or --sort values.priority:asc.",
)
@click.option(
    "--include-archived",
    is_flag=True,
    default=False,
    help="Include archived entries in the result.",
)
@click.option("--limit", default=20, type=int, help="Max results to return (1-200).")
@click.option("--offset", default=0, type=int, help="Offset for pagination.")
@click.option(
    "--include-values",
    is_flag=True,
    default=False,
    help=(
        "Return each entry's full `values` subdocument (raw ff_* keys). "
        "Avoids a per-entry get to fetch field values."
    ),
)
@click.option(
    "--select-value",
    "select_values_raw",
    multiple=True,
    help=(
        "Return only the named field under `values`. Pass multiple times to "
        "select more than one. Accepts either a field key (ff_*) or the "
        "human label (case-insensitive). Implies --include-values."
    ),
)
@click.option(
    "--fields",
    "fields_csv",
    default=None,
    help=(
        "Comma-separated field keys/labels to return under `values` "
        "(e.g. --fields status,owner). Convenience alias for repeated "
        "--select-value; both may be combined. Implies --include-values."
    ),
)
@click.option(
    "--resolve-labels",
    is_flag=True,
    default=False,
    help=(
        "Rewrite returned `values` keys from ff_* IDs to their human labels. "
        "Costs one extra schema fetch."
    ),
)
@pass_context
def list_entries(
    ctx,
    definition_id,
    filters_raw,
    sort_raw,
    include_archived,
    limit,
    offset,
    include_values,
    select_values_raw,
    fields_csv,
    resolve_labels,
):
    """List entries for a definition with optional filtering and sorting."""
    filters = {}
    for pair in filters_raw:
        k, v = _parse_filter_pair(pair)
        filters[k] = v
    if include_archived:
        filters["includeArchived"] = True

    sort = _parse_sort(sort_raw) if sort_raw else None

    # --fields is a comma-separated convenience alias for repeated
    # --select-value; combine both into one projection spec list.
    select_specs = list(select_values_raw)
    if fields_csv:
        select_specs.extend(f.strip() for f in fields_csv.split(",") if f.strip())

    schema_fields = None
    if select_specs or resolve_labels:
        schema_fields = _fetch_schema_fields(ctx, definition_id)

    select_values = None
    if select_specs:
        select_values = _resolve_select_values(select_specs, schema_fields)
        include_values = True

    _do_list(
        ctx,
        type_name="entries",
        definition_id=definition_id,
        filters=filters or None,
        sort=sort,
        limit=limit,
        offset=offset,
        include_values=include_values,
        select_values=select_values,
        schema_fields=schema_fields if resolve_labels else None,
    )


def _fetch_schema_fields(ctx, definition_id):
    """Fetch the definition's schema once, return its `fields` list.

    Reuses the same /api/v1/assets/{id}?format=schema endpoint as
    `upscaler get --format schema`.
    """
    from upscaler_cli.cli.helpers import make_client

    client = make_client(ctx)
    try:
        result = asyncio.run(
            client.request(
                "GET",
                f"/api/v1/assets/{definition_id}",
                params={"format": "schema"},
            )
        )
    except Exception as e:
        handle_error(ctx, e)
        raise click.Abort()
    raise_on_envelope_error(ctx, result)
    schema = result.get("data", {}).get("schema") or {}
    return schema.get("fields") or []


def _resolve_select_values(raw_args, fields):
    """Translate --select-value args (label or ff_* key) to ff_* keys.

    Raises BadParameter on unknown labels, listing valid labels.
    """
    label_to_key = {}
    valid_keys = set()
    for f in fields:
        key = f.get("key")
        label = f.get("label")
        if not key:
            continue
        valid_keys.add(key)
        if label:
            label_to_key[label.casefold()] = key

    valid_labels = sorted(f["label"] for f in fields if f.get("label"))

    resolved = []
    for arg in raw_args:
        if _FIELD_KEY_RE.match(arg):
            if arg not in valid_keys:
                raise click.BadParameter(
                    f"Unknown field key {arg!r}. Valid labels: {valid_labels}"
                )
            resolved.append(arg)
            continue
        key = label_to_key.get(arg.casefold())
        if not key:
            raise click.BadParameter(
                f"Unknown field {arg!r}. Valid labels: {valid_labels}"
            )
        resolved.append(key)
    return resolved


@list_group.command("todos")
@pass_context
def list_todos(ctx):
    """List your todos."""
    _do_list(ctx, type_name="todos")


@list_group.command("members")
@click.option("--search", default=None, help="Search members by name or email.")
@click.option("--show-disabled", is_flag=True, default=False, help="Include disabled members.")
@click.option("--limit", default=20, type=int, help="Max results to return.")
@click.option("--offset", default=0, type=int, help="Offset for pagination.")
@pass_context
def list_members_cmd(ctx, search, show_disabled, limit, offset):
    """List organization members (requires OWNER/ADMIN).

    Use this to discover member IDs for todo assignment and comment @mentions.
    """
    params = {"limit": limit, "offset": offset}
    if search:
        params["search"] = search
    if show_disabled:
        params["show_disabled"] = "true"
    _do_rest_list(
        ctx, "/api/v1/members", params, human_columns=["id", "name", "email", "role"]
    )


@list_group.command("groups")
@pass_context
def list_groups_cmd(ctx):
    """List organization groups (requires OWNER/ADMIN)."""
    _do_rest_list(ctx, "/api/v1/groups", {}, human_columns=["id", "name"])


@list_group.command("deleted")
@click.option("--search", default=None, help="Search deleted assets by title.")
@pass_context
def list_deleted_cmd(ctx, search):
    """List soft-deleted assets (recovery targets; requires OWNER/ADMIN).

    Pair with `upscaler recover <id>` to restore an asset.
    """
    params = {}
    if search:
        params["search"] = search
    _do_rest_list(
        ctx,
        "/api/v1/trash",
        params,
        human_columns=["id", "title", "assetType", "deletedAt", "deletedBy"],
    )


@list_group.command("field-options")
@click.option("--definition-id", required=True, help="Definition ID.")
@click.option("--field-key", required=True, help="Field key to get options for.")
@pass_context
def list_field_options(ctx, definition_id, field_key):
    """List field options for a definition field."""
    _do_list(ctx, type_name="field_options", definition_id=definition_id, field_key=field_key)


def _do_list(
    ctx,
    type_name,
    definition_id=None,
    field_key=None,
    filters=None,
    sort=None,
    limit=None,
    offset=None,
    include_values=False,
    select_values=None,
    schema_fields=None,
):
    """Shared list implementation."""
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json
    from upscaler_cli.formatters.table import format_table

    client = make_client(ctx)

    params = {"type": type_name}
    if definition_id:
        params["definition_id"] = definition_id
    if field_key:
        params["field_key"] = field_key
    if filters:
        params["filters"] = json.dumps(filters)
    if sort:
        params["sort"] = json.dumps(sort)
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if include_values:
        params["include_values"] = "true"
    if select_values:
        params["select_values"] = list(select_values)

    try:
        result = asyncio.run(client.request("GET", "/api/v1/list", params=params))
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    if schema_fields:
        _rewrite_values_to_labels(result, schema_fields)

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        data = result.get("data", [])
        if isinstance(data, dict):
            data = data.get("items", [data])
        if not data:
            click.echo("No results.")
            return
        if type_name == "todos":
            data = _flatten_todo_bookmarks(data)
        click.echo(format_table(data))


def _flatten_todo_bookmarks(items):
    """Flatten each todo's `extra` blob to a plain `bookmark` column.

    The human table cannot render the nested `extra` dict, so drop it and, when
    any todo in the page carries a bookmark, surface `extra.bookmarkUrl` as a
    `bookmark` column. When none are bookmarked, no bookmark column is added so
    the table gains no empty column. JSON output is untouched.
    """
    def _bookmark(item):
        extra = item.get("extra")
        if isinstance(extra, dict):
            return extra.get("bookmarkUrl") or ""
        return ""

    any_bookmark = any(isinstance(it, dict) and _bookmark(it) for it in items)
    flattened = []
    for it in items:
        if not isinstance(it, dict):
            flattened.append(it)
            continue
        row = {k: v for k, v in it.items() if k != "extra"}
        if any_bookmark:
            row["bookmark"] = _bookmark(it)
        flattened.append(row)
    return flattened


def _project_columns(items, columns):
    """Reduce each item dict to the named columns for a focused human table.

    Nested principal objects (e.g. deletedBy: {id, name}) collapse to their
    name so the table stays one value per cell. JSON mode keeps the full shape.
    """
    projected = []
    for item in items:
        if not isinstance(item, dict):
            projected.append(item)
            continue
        row = {}
        for col in columns:
            value = item.get(col)
            if isinstance(value, dict):
                value = value.get("name") or value.get("id") or value
            row[col] = value
        projected.append(row)
    return projected


def _do_rest_list(ctx, path, params, human_columns=None):
    """GET a REST list endpoint and render its {items, total} envelope.

    Unlike _do_list (which targets /api/v1/list), this hits a dedicated list
    route (members/groups/trash). Human output can be projected to a focused
    column set; --json always returns the full envelope.
    """
    from upscaler_cli.cli.helpers import make_client
    from upscaler_cli.formatters.json_fmt import format_json
    from upscaler_cli.formatters.table import format_table

    client = make_client(ctx)
    try:
        result = asyncio.run(client.request("GET", path, params=params or None))
    except Exception as e:
        handle_error(ctx, e)
        return

    raise_on_envelope_error(ctx, result)

    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
        return

    data = result.get("data", [])
    if isinstance(data, dict):
        data = data.get("items", [data])
    if not data:
        click.echo("No results.")
        return
    if human_columns:
        data = _project_columns(data, human_columns)
    click.echo(format_table(data))


def _relabel_nested(value, subid_to_label):
    """Recurse into table rows / composite (date-range) sub-values.

    Table/composite values are dicts (or lists of dicts) keyed by the column's
    trailing sub-id; rewrite those sub-ids to their column labels. Scalars pass
    through unchanged.
    """
    if isinstance(value, dict):
        return {
            subid_to_label.get(sub_k, sub_k): _relabel_nested(sub_v, subid_to_label)
            for sub_k, sub_v in value.items()
        }
    if isinstance(value, list):
        return [_relabel_nested(item, subid_to_label) for item in value]
    return value


def _rewrite_values_to_labels(result, schema_fields):
    """Rewrite each item's `values` keys from ff_* IDs to human labels.

    Handles three field shapes:
    - scalar fields: schema `key` is a bare `ff_...` matching the values key.
    - table / composite fields: schema `key` is prefixed `values.ff_...` (the
      values dict uses the bare `ff_...`), and the value is a dict or list of
      dicts keyed by a column sub-id; `columns[].key` is `values.ff_....<subid>`.
    Both the field key and nested column sub-ids are resolved. Unmapped keys
    are left as-is to tolerate schema drift mid-paginate.
    """
    key_to_label = {}
    subid_to_label = {}
    for field in schema_fields:
        key = field.get("key")
        label = field.get("label")
        if key and label:
            key_to_label[key] = label
            # Table/composite field keys carry a `values.` prefix that the
            # item's values dict does not; map the bare form too.
            if key.startswith("values."):
                key_to_label[key[len("values."):]] = label
        for col in field.get("columns") or []:
            col_key = col.get("key")
            col_label = col.get("label")
            if col_key and col_label:
                subid_to_label[col_key.rsplit(".", 1)[-1]] = col_label

    data = result.get("data") if isinstance(result, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return
    for item in items:
        values = item.get("values") if isinstance(item, dict) else None
        if not isinstance(values, dict):
            continue
        item["values"] = {
            key_to_label.get(k, k): _relabel_nested(v, subid_to_label)
            for k, v in values.items()
        }
