"""File-upload helper for the Upscaler CLI/SDK.

``presign_and_upload`` presigns a multipart S3 POST via /api/v1/files/presign
and streams the file body to S3. Returns the persisted file-item dict in the
canonical shape consumed by the backend's mergeItemValues / saveTaskDraft.

``append_file_to_slate_block`` and ``append_file_to_form_field`` splice the
returned file-item into Pattern A (Slate tree) and Pattern B (flat dict)
values. Both are idempotent on ``uid``.

The persisted shape (``FILE_ITEM_PERSIST_FIELDS``) MUST match
``packages/backend/src/shared/service/asset/normalizeFileBlocks.js``; the
backend normalizer drops anything else.
"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

# Persisted fields on every file-item in a fileList. Mirrors
# `FILE_ITEM_PERSIST_FIELDS` in
# packages/backend/src/shared/service/asset/normalizeFileBlocks.js.
FILE_ITEM_PERSIST_FIELDS = ("uid", "name", "type", "size", "addedAt")


class UploadError(Exception):
    """Raised when a presign or S3 upload step fails."""


class FieldNotFoundError(Exception):
    """Raised when no matching file node/field is found.

    ``available_fields`` lists every file-node name discovered, so the CLI can
    surface "did you mean ...?" guidance without an extra lookup.
    """

    def __init__(self, field_name: str, available_fields: List[str]):
        self.field_name = field_name
        self.available_fields = available_fields
        msg = (
            f'No file field named "{field_name}" on this entry. '
            f"Available file fields: {', '.join(available_fields) or '(none)'}."
        )
        super().__init__(msg)


# Common developer-doc and code extensions that Python's `mimetypes` module
# either doesn't know about (e.g. .md) or maps to a value the backend allowlist
# rejects. Every entry here MUST be present in
# packages/backend/src/shared/constants.js::INTERNAL_FILE_UPLOAD_ALLOWED_TYPES;
# the test in tests/test_uploads.py locks the pairing.
_EXTENSION_OVERRIDES: Dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xml": "text/xml",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".rtf": "text/rtf",
}


def _guess_content_type(file_name: str, override: Optional[str]) -> str:
    if override:
        return override
    suffix = Path(file_name).suffix.lower()
    if suffix in _EXTENSION_OVERRIDES:
        return _EXTENSION_OVERRIDES[suffix]
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def _make_file_item(uid: str, file_name: str, content_type: str, size: int) -> Dict[str, Any]:
    return {
        "uid": uid,
        "name": file_name,
        "type": content_type,
        "size": size,
        "addedAt": datetime.now(timezone.utc).isoformat(),
    }


async def presign_and_upload(
    client: Any,
    *,
    file_name: str,
    content_type: Optional[str],
    file_bytes: bytes,
    asset_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Presign and POST one file to S3.

    Args:
        client: ``UpscalerClient`` (or any object exposing async ``request``).
        file_name: Original filename.
        content_type: MIME type override; falls back to mimetypes guess then
            ``application/octet-stream``.
        file_bytes: Raw file contents.
        asset_id: Target asset id. Required by the REST endpoint so the backend
            can run the per-asset write-permission check. Kept Optional here
            for unit tests that don't need an asset.

    Returns:
        Dict shaped like ``FILE_ITEM_PERSIST_FIELDS``.

    Raises:
        UploadError: On presign failure or S3 upload failure (HTTP >= 300).
    """
    resolved_type = _guess_content_type(file_name, content_type)

    presign_body: Dict[str, Any] = {
        "file_name": file_name,
        "content_type": resolved_type,
    }
    if asset_id:
        presign_body["asset_id"] = asset_id
    try:
        envelope = await client.request(
            "POST",
            "/api/v1/files/presign",
            json=presign_body,
        )
    except Exception as exc:
        # Surface the verbatim server message on 429 so the user sees the
        # actionable "Rate-limited, wait N seconds" string instead of a
        # generic "Presign request failed" prefix.
        status = getattr(exc, "status_code", None)
        if status == 429:
            raise UploadError(str(exc)) from exc
        raise UploadError(f"Presign request failed for {file_name}: {exc}") from exc

    if not envelope.get("success"):
        raise UploadError(
            f"Presign failed for {file_name}: {envelope.get('error') or 'unknown error'}"
        )

    data = envelope.get("data") or {}
    uid = data.get("uid")
    url = data.get("url")
    fields = data.get("fields") or {}
    if not uid or not url:
        raise UploadError(f"Presign envelope missing uid/url for {file_name}")

    # S3 multipart POST: policy fields go in `data`, the file body goes in
    # `files` keyed "file" per the AWS presigned POST spec. The backend
    # includes `Content-Type` in `fields`, so we don't prepend it.
    try:
        async with httpx.AsyncClient(timeout=60.0) as s3:
            response = await s3.post(
                url,
                data=fields,
                files={"file": (file_name, file_bytes, resolved_type)},
            )
    except Exception as exc:
        raise UploadError(f"S3 upload failed for {file_name}: {exc}") from exc

    if response.status_code >= 300:
        raise UploadError(
            f"S3 upload failed for {file_name}: "
            f"HTTP {response.status_code} {response.text[:200]}"
        )

    return _make_file_item(uid, file_name, resolved_type, len(file_bytes))


def _is_file_node(node: Any) -> bool:
    return isinstance(node, dict) and node.get("type") == "file"


def _collect_file_field_names(values: Iterable[Any], out: List[str]) -> List[str]:
    if not isinstance(values, list):
        return out
    for node in values:
        if not isinstance(node, dict):
            continue
        if _is_file_node(node):
            name = (node.get("options") or {}).get("name")
            if name:
                out.append(name)
        children = node.get("children")
        if isinstance(children, list):
            _collect_file_field_names(children, out)
    return out


def _walk_and_append(
    values: List[Any],
    field_name: str,
    file_item: Dict[str, Any],
) -> tuple[List[Any], bool]:
    """Return (new_values, found). new_values is a shallow-copied tree with the
    target file node's fileList updated. ``found`` is False when no file node
    with options.name == field_name was located in this branch.
    """
    found = False
    new_nodes: List[Any] = []
    for node in values:
        if not isinstance(node, dict):
            new_nodes.append(node)
            continue

        next_node: Dict[str, Any] = node
        if _is_file_node(node):
            name = (node.get("options") or {}).get("name")
            if name == field_name:
                existing = list(node.get("fileList") or [])
                uids = {item.get("uid") for item in existing if isinstance(item, dict)}
                if file_item["uid"] not in uids:
                    existing.append(dict(file_item))
                next_node = {**node, "fileList": existing}
                found = True

        children = next_node.get("children")
        if isinstance(children, list):
            new_children, child_found = _walk_and_append(children, field_name, file_item)
            if child_found:
                next_node = {**next_node, "children": new_children}
                found = True

        new_nodes.append(next_node)
    return new_nodes, found


def append_file_to_form_field(
    values: Dict[str, Any],
    ff_key: str,
    file_item: Dict[str, Any],
) -> Dict[str, Any]:
    """Append ``file_item`` to ``values[ff_key]`` on a Pattern B form-upload dict.

    Items + Records persist ``values`` as a flat dict keyed by ``ff_*``. Each
    form-upload field's value is a list of File Items. This walker returns a
    shallow-copied dict with the new file appended to the named field's array.

    Idempotent on ``uid``: a duplicate is silently dropped so the conflict-retry
    loop (FR-014) can re-apply the same append without creating duplicates.
    """
    if not isinstance(values, dict):
        raise FieldNotFoundError(ff_key, [])

    existing = values.get(ff_key)
    if existing is None:
        # First file for this field; the caller has already validated ff_key
        # against the schema, so create the list.
        existing = []
    elif not isinstance(existing, list):
        # ff_key exists but is not a list (e.g. a text field). Caller mis-routed.
        raise FieldNotFoundError(ff_key, sorted(values.keys()))

    uids = {item.get("uid") for item in existing if isinstance(item, dict)}
    if file_item["uid"] in uids:
        return values

    return {**values, ff_key: [*existing, dict(file_item)]}


def append_row_to_table_field(
    values: Dict[str, Any],
    table_key: str,
    row: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Append one new row to a Pattern B form-table field.

    Tables persist as ``values[table_key] = [{col_key: <col_value>, ...}, ...]``.
    Each row is an independent dict. This helper preserves every existing row
    and appends ``row`` as the last entry; the caller is responsible for
    composing ``row`` (a dict keyed by column ``ff_*`` with file-item lists
    as values).

    Idempotent on file ``uid``: if any existing row already contains every
    uid in ``row`` (matched per column), the value is returned unchanged so
    the conflict-retry loop can re-apply without producing duplicate rows.
    """
    if not isinstance(values, dict):
        raise FieldNotFoundError(table_key, [])

    existing_rows = values.get(table_key)
    if existing_rows is None:
        existing_rows = []
    elif not isinstance(existing_rows, list):
        raise FieldNotFoundError(table_key, sorted(values.keys()))

    new_uids = _collect_row_uids(row)
    if new_uids:
        for prior in existing_rows:
            if not isinstance(prior, dict):
                continue
            if new_uids <= _collect_row_uids(prior):
                return values

    return {**values, table_key: [*existing_rows, _copy_row(row)]}


def _collect_row_uids(row: Dict[str, Any]) -> set:
    """Set of uids across every file-list column in ``row``."""
    uids: set = set()
    for col_value in row.values():
        if isinstance(col_value, list):
            for item in col_value:
                if isinstance(item, dict) and item.get("uid"):
                    uids.add(item["uid"])
    return uids


def _copy_row(row: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        col_key: [dict(item) for item in items]
        for col_key, items in row.items()
    }


def append_file_to_slate_block(
    values: Any,
    field_name: str,
    file_item: Dict[str, Any],
) -> List[Any]:
    """Pattern A. Append ``file_item`` to the Slate file node named ``field_name``.

    Used for Documents (slice 7). Items + Records use Pattern B
    (``append_file_to_form_field``).

    Idempotent on ``uid``: a duplicate is silently dropped so the SDK's
    conflict-retry loop (FR-014) can re-apply the same append without creating
    duplicates.

    Raises:
        FieldNotFoundError: if no file node matches.
    """
    if not isinstance(values, list):
        raise FieldNotFoundError(field_name, [])

    new_values, found = _walk_and_append(values, field_name, file_item)
    if not found:
        available = _collect_file_field_names(values, [])
        raise FieldNotFoundError(field_name, available)
    return new_values
