"""Tests for the file-upload helper.

Covers:
- ``FILE_ITEM_PERSIST_FIELDS`` shape parity with the backend normalizer.
- ``append_file_to_slate_block`` cases: valid, unknown, duplicate uid, multiple file
  nodes, empty tree, non-Slate values.
- ``presign_and_upload`` happy path and error paths (mocked client + S3).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from upscaler_cli.uploads import (
    FILE_ITEM_PERSIST_FIELDS,
    FieldNotFoundError,
    UploadError,
    append_file_to_form_field,
    append_file_to_slate_block,
    append_row_to_table_field,
    presign_and_upload,
)

# ---------------------------------------------------------------------------
# Shape parity with backend normalizer (T043)
# ---------------------------------------------------------------------------


class TestShapeParity:
    """Locks FILE_ITEM_PERSIST_FIELDS against the backend normalizer.

    The backend's `normalizeFileBlocks.js` picks exactly these keys off every
    uploaded file item and drops the rest, so a CLI that sends a different
    shape silently loses data. The backend is closed-source, so the expected
    tuple is mirrored here rather than parsed out of its source. Update both
    together, same as `TestContentTypeAutoguess._BACKEND_ALLOWLIST` below.
    """

    # Mirrors FILE_ITEM_PERSIST_FIELDS in the backend's
    # src/shared/service/asset/normalizeFileBlocks.js.
    _BACKEND_PERSIST_FIELDS = ("uid", "name", "type", "size", "addedAt")

    def test_persist_fields_match_backend(self):
        assert FILE_ITEM_PERSIST_FIELDS == self._BACKEND_PERSIST_FIELDS


# ---------------------------------------------------------------------------
# append_file_to_slate_block (T042 + T044)
# ---------------------------------------------------------------------------


def _file_node(name, file_list=None):
    return {
        "type": "file",
        "options": {"name": name},
        "fileList": list(file_list or []),
        "children": [{"text": ""}],
    }


def _file_item(uid="u_new", name="report.pdf"):
    return {
        "uid": uid,
        "name": name,
        "type": "application/pdf",
        "size": 1024,
        "addedAt": "2026-05-25T00:00:00+00:00",
    }


class TestAppendFileToSlateBlock:
    def test_appends_to_matching_field(self):
        values = [_file_node("evidence")]
        result = append_file_to_slate_block(values, "evidence", _file_item("u_1"))
        node = result[0]
        assert len(node["fileList"]) == 1
        assert node["fileList"][0]["uid"] == "u_1"

    def test_unknown_field_raises_with_available_list(self):
        values = [_file_node("evidence"), _file_node("photo")]
        with pytest.raises(FieldNotFoundError) as exc:
            append_file_to_slate_block(values, "missing", _file_item())
        assert exc.value.field_name == "missing"
        assert set(exc.value.available_fields) == {"evidence", "photo"}
        assert "evidence" in str(exc.value)
        assert "photo" in str(exc.value)

    def test_duplicate_uid_is_idempotent(self):
        values = [_file_node("evidence", [_file_item("u_1")])]
        result = append_file_to_slate_block(values, "evidence", _file_item("u_1"))
        assert len(result[0]["fileList"]) == 1

    def test_multiple_file_nodes_in_tree(self):
        values = [_file_node("evidence"), _file_node("photo")]
        result = append_file_to_slate_block(values, "photo", _file_item("u_p"))
        assert len(result[0]["fileList"]) == 0  # evidence untouched
        assert len(result[1]["fileList"]) == 1
        assert result[1]["fileList"][0]["uid"] == "u_p"

    def test_nested_file_node_in_children(self):
        values = [
            {
                "type": "section",
                "children": [_file_node("evidence")],
            }
        ]
        result = append_file_to_slate_block(values, "evidence", _file_item("u_1"))
        nested = result[0]["children"][0]
        assert len(nested["fileList"]) == 1
        assert nested["fileList"][0]["uid"] == "u_1"

    def test_empty_tree_raises(self):
        with pytest.raises(FieldNotFoundError) as exc:
            append_file_to_slate_block([], "evidence", _file_item())
        assert exc.value.available_fields == []

    def test_non_slate_values_raises(self):
        with pytest.raises(FieldNotFoundError):
            append_file_to_slate_block({"not": "a list"}, "evidence", _file_item())

    def test_does_not_mutate_input(self):
        values = [_file_node("evidence")]
        original = [_file_node("evidence")]
        append_file_to_slate_block(values, "evidence", _file_item())
        assert values == original


# append_file_to_form_field (Pattern B, Items + Records).


class TestAppendFileToFormField:
    def test_appends_to_existing_array(self):
        # Item.values is a flat dict keyed by ff_*. Each form-upload field's
        # value is a list of File Items; append a new uid onto that list.
        values = {"ff_a": [_file_item("u_existing")], "ff_n": "notes"}
        result = append_file_to_form_field(values, "ff_a", _file_item("u_new"))
        assert result["ff_a"] == [_file_item("u_existing"), _file_item("u_new")]
        # Other keys preserved verbatim.
        assert result["ff_n"] == "notes"

    def test_creates_array_when_field_absent(self):
        # First file uploaded to a form-upload field: ff_key isn't present in
        # values yet. Walker creates the list rather than raising; the schema
        # check upstream already proved the field is valid.
        values = {"ff_n": "notes"}
        result = append_file_to_form_field(values, "ff_a", _file_item("u_new"))
        assert result["ff_a"] == [_file_item("u_new")]
        assert result["ff_n"] == "notes"

    def test_duplicate_uid_is_idempotent(self):
        # Conflict-retry replays the same append against refreshed values; the
        # walker must dedupe on uid so retries don't accumulate copies.
        values = {"ff_a": [_file_item("u_dup")]}
        result = append_file_to_form_field(values, "ff_a", _file_item("u_dup"))
        assert len(result["ff_a"]) == 1

    def test_does_not_mutate_input(self):
        # Functional contract: input dict + nested list must be untouched so
        # callers can rely on the returned value as the new source of truth.
        values = {"ff_a": [_file_item("u_1")], "ff_n": "notes"}
        snapshot = {"ff_a": [_file_item("u_1")], "ff_n": "notes"}
        append_file_to_form_field(values, "ff_a", _file_item("u_new"))
        assert values == snapshot

    def test_misrouted_key_raises_with_available_list(self):
        # ff_n exists but is a text field (string value, not a list). Caller
        # mis-routed: surface a FieldNotFoundError with the list of dict keys
        # so the CLI can show "did you mean ...?".
        values = {"ff_a": [_file_item("u_1")], "ff_n": "notes"}
        with pytest.raises(FieldNotFoundError) as exc:
            append_file_to_form_field(values, "ff_n", _file_item("u_new"))
        assert exc.value.field_name == "ff_n"
        assert "ff_a" in exc.value.available_fields


# ---------------------------------------------------------------------------
# append_row_to_table_field: Pattern B form-table row append
# ---------------------------------------------------------------------------


class TestAppendRowToTableField:
    def test_creates_table_list_when_field_absent(self):
        result = append_row_to_table_field(
            {}, "ff_table", {"ff_file": [_file_item("u_a")]}
        )
        assert result["ff_table"] == [{"ff_file": [_file_item("u_a")]}]

    def test_preserves_existing_rows(self):
        existing = [{"ff_file": [_file_item("u_pre")]}]
        result = append_row_to_table_field(
            {"ff_table": existing}, "ff_table",
            {"ff_file": [_file_item("u_new")]},
        )
        assert len(result["ff_table"]) == 2
        assert result["ff_table"][0]["ff_file"][0]["uid"] == "u_pre"
        assert result["ff_table"][1]["ff_file"][0]["uid"] == "u_new"

    def test_idempotent_when_row_uids_already_in_table(self):
        # The conflict-retry loop re-applies the splice spec against fresh
        # server values. If a row carrying our uid is already present (which
        # only happens if the prior attempt actually landed), skip rather
        # than duplicate.
        existing = [{"ff_file": [_file_item("u_new")]}]
        result = append_row_to_table_field(
            {"ff_table": existing}, "ff_table",
            {"ff_file": [_file_item("u_new")]},
        )
        assert result == {"ff_table": existing}

    def test_does_not_mutate_input(self):
        original = {"ff_table": [{"ff_file": [_file_item("u_pre")]}]}
        snapshot = {"ff_table": [{"ff_file": [_file_item("u_pre")]}]}
        append_row_to_table_field(
            original, "ff_table", {"ff_file": [_file_item("u_new")]}
        )
        assert original == snapshot

    def test_misrouted_key_raises(self):
        # ff_table exists but is not a list (someone passed a top-level file
        # field). Surface the available keys so the CLI can hint the caller.
        values = {"ff_a": "string"}
        with pytest.raises(FieldNotFoundError):
            append_row_to_table_field(values, "ff_a", {"ff_file": [_file_item("u_x")]})


# ---------------------------------------------------------------------------
# presign_and_upload (T041)
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, envelope):
        self.envelope = envelope
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.envelope


class _Response:
    def __init__(self, status_code=204, text=""):
        self.status_code = status_code
        self.text = text


class TestPresignAndUpload:
    def _make_envelope(self, **overrides):
        data = {
            "uid": "u_new",
            "url": "https://org.s3.eu-west-1.amazonaws.com",
            "fields": {"key": "u_new", "Policy": "<x>", "Tagging": "<x/>"},
            "bucket": "org",
            "expires_in": 120,
        }
        data.update(overrides)
        return {"success": True, "data": data, "error": None}

    @patch("upscaler_cli.uploads.httpx.AsyncClient")
    def test_happy_path_returns_file_item(self, mock_httpx_factory):
        client = _FakeClient(self._make_envelope())

        s3_async = AsyncMock()
        s3_async.post = AsyncMock(return_value=_Response(204))
        mock_httpx_factory.return_value.__aenter__.return_value = s3_async

        result = asyncio.run(
            presign_and_upload(
                client,
                file_name="report.pdf",
                content_type="application/pdf",
                file_bytes=b"hello world",
            )
        )

        assert result["uid"] == "u_new"
        assert result["name"] == "report.pdf"
        assert result["type"] == "application/pdf"
        assert result["size"] == len(b"hello world")
        assert result["addedAt"]

        # Verify presign call shape
        method, path, kwargs = client.calls[0]
        assert method == "POST"
        assert path == "/api/v1/files/presign"
        assert kwargs["json"]["file_name"] == "report.pdf"
        assert kwargs["json"]["content_type"] == "application/pdf"

    @patch("upscaler_cli.uploads.httpx.AsyncClient")
    def test_autodetects_content_type(self, mock_httpx_factory):
        client = _FakeClient(self._make_envelope())
        s3_async = AsyncMock()
        s3_async.post = AsyncMock(return_value=_Response(204))
        mock_httpx_factory.return_value.__aenter__.return_value = s3_async

        result = asyncio.run(
            presign_and_upload(
                client,
                file_name="report.pdf",
                content_type=None,
                file_bytes=b"hello",
            )
        )
        assert result["type"] == "application/pdf"

    @patch("upscaler_cli.uploads.httpx.AsyncClient")
    def test_unknown_extension_falls_back_to_octet_stream(self, mock_httpx_factory):
        client = _FakeClient(self._make_envelope())
        s3_async = AsyncMock()
        s3_async.post = AsyncMock(return_value=_Response(204))
        mock_httpx_factory.return_value.__aenter__.return_value = s3_async

        result = asyncio.run(
            presign_and_upload(
                client,
                file_name="payload.weirdext",
                content_type=None,
                file_bytes=b"hello",
            )
        )
        assert result["type"] == "application/octet-stream"

    def test_failed_envelope_raises_upload_error(self):
        client = _FakeClient({"success": False, "error": "no scope", "data": None})
        with pytest.raises(UploadError) as exc:
            asyncio.run(
                presign_and_upload(
                    client,
                    file_name="report.pdf",
                    content_type=None,
                    file_bytes=b"hello",
                )
            )
        assert "no scope" in str(exc.value)

    def test_rate_limited_response_preserves_message(self):
        # When the server returns 429 with a "Rate-limited..." body, the SDK
        # must surface that message verbatim instead of collapsing it into a
        # generic prefix. The CLI relies on this string to give the user
        # something actionable.
        from upscaler_cli.errors import APIError

        class _RateLimitedClient:
            async def request(self, *args, **kwargs):
                raise APIError(
                    "Rate-limited — wait 30 seconds before retrying.",
                    status_code=429,
                )

        with pytest.raises(UploadError) as exc:
            asyncio.run(
                presign_and_upload(
                    _RateLimitedClient(),
                    file_name="report.pdf",
                    content_type="application/pdf",
                    file_bytes=b"hello",
                )
            )
        assert "Rate-limited" in str(exc.value)
        # Make sure we don't prepend the generic "Presign request failed" noise.
        assert "Presign request failed" not in str(exc.value)

    @patch("upscaler_cli.uploads.httpx.AsyncClient")
    def test_s3_failure_raises_upload_error(self, mock_httpx_factory):
        client = _FakeClient(self._make_envelope())
        s3_async = AsyncMock()
        s3_async.post = AsyncMock(return_value=_Response(500, text="AccessDenied"))
        mock_httpx_factory.return_value.__aenter__.return_value = s3_async

        with pytest.raises(UploadError) as exc:
            asyncio.run(
                presign_and_upload(
                    client,
                    file_name="report.pdf",
                    content_type="application/pdf",
                    file_bytes=b"hello",
                )
            )
        assert "AccessDenied" in str(exc.value) or "500" in str(exc.value)


class TestContentTypeAutoguess:
    """Locks the _EXTENSION_OVERRIDES map against the backend allowlist.

    Background: Python's `mimetypes` doesn't know `.md` and falls back to
    `application/octet-stream`, which the backend's
    `INTERNAL_FILE_UPLOAD_ALLOWED_TYPES` rejects. The override map fixes the
    common developer-doc extensions; this test ensures every override stays
    in the allowlist (no orphan entries that would 500 on first use).
    """

    # Mirrors INTERNAL_FILE_UPLOAD_ALLOWED_TYPES from
    # packages/backend/src/shared/constants.js (kept minimal: only the values
    # this test verifies). Update both files together.
    _BACKEND_ALLOWLIST = {
        "text/markdown",
        "text/plain",
        "text/csv",
        "text/tab-separated-values",
        "application/json",
        "text/xml",
        "text/yaml",
        "text/rtf",
    }

    def test_md_autoguesses_to_text_markdown(self):
        from upscaler_cli.uploads import _guess_content_type

        assert _guess_content_type("notes.md", None) == "text/markdown"
        assert _guess_content_type("README.MARKDOWN", None) == "text/markdown"

    def test_explicit_override_still_wins(self):
        from upscaler_cli.uploads import _guess_content_type

        # User-passed --content-type wins over the override map.
        assert _guess_content_type("notes.md", "text/plain") == "text/plain"

    def test_every_override_is_on_backend_allowlist(self):
        from upscaler_cli.uploads import _EXTENSION_OVERRIDES

        for ext, mime in _EXTENSION_OVERRIDES.items():
            assert mime in self._BACKEND_ALLOWLIST, (
                f"_EXTENSION_OVERRIDES['{ext}'] -> '{mime}' is not on the "
                "backend allowlist. Either remove the override or add the MIME "
                "to INTERNAL_FILE_UPLOAD_ALLOWED_TYPES in backend constants.js."
            )

    def test_unknown_extension_falls_through_to_mimetypes(self):
        from upscaler_cli.uploads import _guess_content_type

        # .pdf isn't in the override map; mimetypes should resolve it.
        assert _guess_content_type("report.pdf", None) == "application/pdf"
