"""Integration tests for `upscaler entry update --file` and `entry upload-file`.

All HTTP interactions are mocked. Items and Records persist values as a flat
dict keyed by ff_* (Pattern B, per ADR-008), so the fixtures here use that
shape, not a Slate tree. The CLI is responsible for resolving a human field
title to ff_* via the schema endpoint before any S3 traffic.
"""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.entry import entry_group

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeUpscalerClient:
    """In-memory client that scripts responses by (method, path) prefix.

    Pop responses off the queue when matched; raise AssertionError if a call
    has no scripted response (catches accidental extra requests).
    """

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.script: list[tuple[tuple[str, str], object]] = []

    def expect(self, method, path_prefix, response):
        self.script.append(((method, path_prefix), response))

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        for idx, ((m, p), resp) in enumerate(self.script):
            if m == method and path.startswith(p):
                self.script.pop(idx)
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"Unscripted call: {method} {path}. Remaining: {self.script}")


@pytest.fixture
def fake_client():
    return FakeUpscalerClient()


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_file(tmp_path):
    p = tmp_path / "report.pdf"
    p.write_bytes(b"%PDF-1.4 test")
    return p


# ---------------------------------------------------------------------------
# Fixtures: Pattern B shapes
# ---------------------------------------------------------------------------


def _schema_response(fields):
    """Slice 4 /api/v1/assets/{id}/schema response."""
    return {
        "success": True,
        "data": {"registerId": "rg_test", "fields": fields},
        "error": None,
    }


def _entry_envelope(values, version="3"):
    """/api/v1/assets/{id} response. Items return values as a flat dict."""
    return {
        "success": True,
        "data": {"id": "i_test", "version": version, "values": values},
        "error": None,
    }


def _presign_envelope(uid="u_uploaded"):
    return {
        "success": True,
        "data": {
            "uid": uid,
            "url": "https://example.s3.amazonaws.com",
            "fields": {"key": uid, "Policy": "<x>"},
            "bucket": "example",
            "expires_in": 120,
        },
        "error": None,
    }


def _entries_success(entry_id="i_test"):
    return {"success": True, "data": {"id": entry_id}, "error": None}


def _evidence_schema(extra_fields=()):
    base = [
        {"key": "ff_a", "label": "Evidence", "type": "file_upload"},
        {"key": "ff_b", "label": "Photos", "type": "file_upload"},
        {"key": "ff_n", "label": "Notes", "type": "form-text"},
    ]
    return _schema_response(base + list(extra_fields))


def _support_docs_table(extra_columns=()):
    """A form-table field shaped per form-table.js::toAgentSchema output.

    Two file_upload columns by default ("File", "Cover") so tests can exercise
    same-table multi-column merges. extra_columns appends to the column list.
    """
    return {
        "key": "ff_table",
        "label": "Support documents",
        "type": "table",
        "columns": [
            {"key": "ff_file", "label": "File", "type": "file_upload"},
            {"key": "ff_cover", "label": "Cover", "type": "file_upload"},
            *list(extra_columns),
        ],
    }


def _support_docs_table_dotted(extra_columns=()):
    """A form-table as the LIVE `/api/v1/assets/{id}/schema` endpoint returns it.

    Unlike the bare-keyed `toAgentSchema` shape above, the real schema
    projection reports each column's key as the dotted composite
    ``ff_table.ff_col`` (the flattened form-field key) with a null ``dataIndex``.
    The store and every UI renderer still key rows by the BARE column id, so the
    CLI must reduce to bare before splicing. Regression guard for the
    present-but-invisible-row bug (agent-skills alignment proposal B9); the
    bare-keyed fixture above masked it.
    """
    return {
        "key": "ff_table",
        "label": "Support documents",
        "type": "table",
        "columns": [
            {"key": "ff_table.ff_file", "dataIndex": None, "label": "File", "type": "file_upload"},
            {
                "key": "ff_table.ff_cover",
                "dataIndex": None,
                "label": "Cover",
                "type": "file_upload",
            },
            *list(extra_columns),
        ],
    }


# ---------------------------------------------------------------------------
# S3 mock helper
# ---------------------------------------------------------------------------


class _S3Resp:
    status_code = 204
    text = ""


class _S3Ctx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, *args, **kwargs):
        return _S3Resp()


def _setup_s3_ok(mock_httpx_factory):
    mock_httpx_factory.return_value = _S3Ctx()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestEntryUpdateHappyPaths:
    def test_direct_ff_key_uploads_and_appends_to_flat_dict(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # --field ff_a passes through unchanged; the walker creates the list
        # because the dict has no ff_a key yet.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_x"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"ff_a={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        body = entries[2]["json"]
        assert body["entry_id"] == "i_test"
        assert body["data"]["expectedVersion"] == "3"
        assert body["data"]["values"]["ff_a"][0]["uid"] == "u_x"

    def test_title_resolution_case_insensitive_trimmed(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # --field "  evidence  " resolves to ff_a (the Evidence form-upload
        # field) via case-insensitive trimmed match.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_x"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"  evidence  ={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        assert entries[2]["json"]["data"]["values"]["ff_a"][0]["uid"] == "u_x"

    def test_multiple_files_with_data_overrides(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_path,
    ):
        # Story 1.2: agent updates a text field + uploads two files in one
        # call. One mutation, both uids spliced, text override carried through.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "a.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "b.jpg"
        f2.write_bytes(b"BBB")

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_a"))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_b"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "i_test",
                "--data",
                '{"values": {"ff_n": "Quarterly review attached"}}',
                "--file",
                f"Evidence={f1}",
                "--file",
                f"Photos={f2}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        body = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")[2]["json"]
        values = body["data"]["values"]
        assert values["ff_a"][0]["uid"] == "u_a"
        assert values["ff_b"][0]["uid"] == "u_b"
        assert values["ff_n"] == "Quarterly review attached"

    def test_task_id_routes_to_task_draft_without_expectedVersion(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Story 1.3: record task submit lands as a task draft for human
        # review (A098). expectedVersion is NOT sent (saveTaskDraft retains
        # LWW per FR-013 scope).
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        # Record schema is fetched per-task (?taskId=), and the values to merge
        # into come from the TASK, not the record (records hold no record-level
        # values). The schema expectation matches by prefix so the ?taskId=
        # query string is fine.
        fake_client.expect(
            "GET",
            "/api/v1/assets/r_789/schema",
            _evidence_schema(
                [{"key": "ff_s", "label": "Supporting Documents", "type": "file_upload"}]
            ),
        )
        fake_client.expect(
            "GET",
            "/api/v1/tasks/t_321",
            {"success": True, "data": {"id": "t_321", "values": {}}, "error": None},
        )
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_s"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success("r_789"))

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "r_789",
                "--task-id",
                "t_321",
                "--file",
                f"Supporting Documents={tmp_file}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        # Schema lookup must carry the task id so the backend resolves the
        # task's fields rather than (non-existent) record-level fields.
        schema_call = next(
            c for c in fake_client.calls if c[1].startswith("/api/v1/assets/r_789/schema")
        )
        assert "taskId=t_321" in schema_call[1]
        body = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")[2]["json"]
        assert body["task_id"] == "t_321"
        assert "expectedVersion" not in body["data"]
        assert body["data"]["values"]["ff_s"][0]["uid"] == "u_s"

    def test_record_upload_without_task_id_fails_loud(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # A record holds file fields on tasks; without --task-id there is no
        # task to resolve the field against or to merge values into. Fail before
        # any schema fetch or S3 traffic.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "r_789",
                "--file",
                f"Supporting Documents={tmp_file}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 1
        assert "task-id" in result.output.lower()
        assert fake_client.calls == []

    def test_appends_to_existing_file_field_preserving_history(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Existing files on ff_a must be preserved: the walker appends rather
        # than replaces. Otherwise a CLI upload would silently delete previous
        # web-editor uploads.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        existing = [
            {
                "uid": "u_pre",
                "name": "prior.pdf",
                "type": "application/pdf",
                "size": 100,
                "addedAt": "2026-05-01T00:00:00+00:00",
            },
        ]
        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({"ff_a": existing}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_new"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"ff_a={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        call = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        spliced = call[2]["json"]["data"]["values"]["ff_a"]
        assert [item["uid"] for item in spliced] == ["u_pre", "u_new"]


# ---------------------------------------------------------------------------
# Nested file columns inside a form-table
# ---------------------------------------------------------------------------


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestEntryUpdateNestedTableColumns:
    def test_dotted_label_path_appends_new_row(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # "Support documents.File=path" resolves to (ff_table, ff_file) and
        # appends ONE new row containing the file under ff_file. Existing
        # rows on the table are preserved unchanged.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        existing_rows = [{"ff_file": [{"uid": "u_pre", "name": "prior.pdf"}]}]
        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table()]),
        )
        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test",
            _entry_envelope({"ff_table": existing_rows}),
        )
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_new"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Support documents.File={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        rows = entries[2]["json"]["data"]["values"]["ff_table"]
        # Existing row preserved; new row appended carrying just the file column.
        assert len(rows) == 2
        assert rows[0]["ff_file"][0]["uid"] == "u_pre"
        assert rows[1] == {
            "ff_file": [
                {
                    **rows[1]["ff_file"][0],
                    "uid": "u_new",
                }
            ]
        }
        # Presign forwarded the entry id as asset_id (Bug 1 contract).
        presign = next(c for c in fake_client.calls if c[1] == "/api/v1/files/presign")
        assert presign[2]["json"]["asset_id"] == "i_test"

    def test_dotted_ff_path_resolves_directly(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # ff_table.ff_cover bypasses label matching — the path is taken as-is.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table()]),
        )
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_c"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"ff_table.ff_cover={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries_call = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        rows = entries_call[2]["json"]["data"]["values"]["ff_table"]
        assert rows == [{"ff_cover": [rows[0]["ff_cover"][0]]}]
        assert rows[0]["ff_cover"][0]["uid"] == "u_c"

    def test_multiple_columns_same_table_become_one_row(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_path,
    ):
        # Two --file flags targeting different columns of the SAME table land
        # in ONE new row carrying both columns. This is the agreed "Option A"
        # semantics: per-table grouping rather than per-file rows.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "report.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "cover.png"
        f2.write_bytes(b"BBB")

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table()]),
        )
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_f"))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_c"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "i_test",
                "--file",
                f"Support documents.File={f1}",
                "--file",
                f"Support documents.Cover={f2}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries_call = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        rows = entries_call[2]["json"]["data"]["values"]["ff_table"]
        assert len(rows) == 1
        assert rows[0]["ff_file"][0]["uid"] == "u_f"
        assert rows[0]["ff_cover"][0]["uid"] == "u_c"

    def test_two_files_same_column_share_one_row(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_path,
    ):
        # Two --file flags hitting the same Table.Column → one new row whose
        # column carries both file items.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "a.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "b.pdf"
        f2.write_bytes(b"BBB")

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table()]),
        )
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_a"))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_b"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "i_test",
                "--file",
                f"Support documents.File={f1}",
                "--file",
                f"Support documents.File={f2}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries_call = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        rows = entries_call[2]["json"]["data"]["values"]["ff_table"]
        assert len(rows) == 1
        uids = [item["uid"] for item in rows[0]["ff_file"]]
        assert uids == ["u_a", "u_b"]

    def test_top_level_and_nested_mixed_in_one_call(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_path,
    ):
        # Mixed batch: one top-level field append + one nested row. The two
        # splice branches are independent and both must land in the single
        # PATCH.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "top.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "nested.pdf"
        f2.write_bytes(b"BBB")

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response(
                [
                    {"key": "ff_a", "label": "Evidence", "type": "file_upload"},
                    _support_docs_table(),
                ]
            ),
        )
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_top"))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_nest"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "i_test",
                "--file",
                f"Evidence={f1}",
                "--file",
                f"Support documents.File={f2}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries_call = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        values = entries_call[2]["json"]["data"]["values"]
        assert values["ff_a"][0]["uid"] == "u_top"
        assert values["ff_table"][0]["ff_file"][0]["uid"] == "u_nest"

    def test_unknown_table_fails_loud_before_upload(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Typo on the table half of the dotted path: fail with the available
        # tables listed; no S3 traffic.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table()]),
        )

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Suport docs.File={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        assert "Suport docs" in result.output
        assert "Support documents" in result.output
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)

    def test_unknown_column_fails_loud_before_upload(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Typo on the column half: surface the available file columns inside
        # the table, no S3 traffic.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table()]),
        )

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Support documents.Fyle={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        assert "Fyle" in result.output
        assert "File" in result.output
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)

    def test_top_level_field_pointing_at_table_suggests_dotted_form(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Using --file "Support documents=path" without a column should fail
        # and hint the user to specify a column with TABLE.COLUMN.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table()]),
        )

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Support documents={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        # We don't recover here; the user passed an ambiguous name. Just
        # ensure no S3 upload happened.
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestEntryUpdateDottedSchemaColumnKeys:
    """The live schema reports table columns as dotted `ff_table.ff_col`, but
    the persisted row and UI key cells by the bare `ff_col`. The CLI must splice
    bare regardless of which shape the schema (or the user) supplies.
    Regression guard for the present-but-invisible-row bug (proposal B9)."""

    def test_dotted_label_path_splices_bare_col_key(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # "Support documents.File" against a DOTTED-key schema must still store
        # the row under the bare `ff_file`, never `ff_table.ff_file`.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table_dotted()]),
        )
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_new"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Support documents.File={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        rows = entries[2]["json"]["data"]["values"]["ff_table"]
        assert rows == [{"ff_file": [rows[0]["ff_file"][0]]}]
        assert "ff_table.ff_file" not in rows[0]
        assert rows[0]["ff_file"][0]["uid"] == "u_new"

    def test_dotted_ff_path_resolves_to_bare_against_dotted_schema(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # User passes the dotted raw key `ff_table.ff_cover`; the resolver splits
        # on the first dot (col_raw == "ff_cover"), matches the bare alias, and
        # still stores under the bare `ff_cover`.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table_dotted()]),
        )
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_c"))
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"ff_table.ff_cover={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries = next(c for c in fake_client.calls if c[1] == "/api/v1/entries")
        rows = entries[2]["json"]["data"]["values"]["ff_table"]
        assert rows == [{"ff_cover": [rows[0]["ff_cover"][0]]}]
        assert "ff_table.ff_cover" not in rows[0]
        assert rows[0]["ff_cover"][0]["uid"] == "u_c"

    def test_unknown_column_hint_shows_bare_keys(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # A typo against the dotted schema lists available columns as bare ids,
        # never the doubled `ff_table.ff_table.ff_col` form.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test/schema",
            _schema_response([_support_docs_table_dotted()]),
        )

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Support documents.Fyle={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        assert "ff_file" in result.output
        assert "ff_table.ff_file" not in result.output
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)


# ---------------------------------------------------------------------------
# Fail-loud validation BEFORE any S3 upload
# ---------------------------------------------------------------------------


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestValidationFailsBeforeUpload:
    def test_unknown_title_fails_loud(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Story 1.6: typo'd field name → exit non-zero, print available titles,
        # NO presign call.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        # No further calls scripted: any further call fails the test.

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Evidense={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        # Surfaces the typo and the available titles.
        assert "Evidense" in result.output
        assert "Evidence" in result.output
        # NEVER called presign or entries.
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)
        assert all(c[1] != "/api/v1/entries" for c in fake_client.calls)

    def test_ambiguous_title_fails_loud(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Story 1.7: two form-upload fields share the title "Attachments";
        # CLI must refuse and tell the user to pass --field <ff_id>.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        ambiguous_schema = _schema_response(
            [
                {"key": "ff_x", "label": "Attachments", "type": "file_upload"},
                {"key": "ff_y", "label": "Attachments", "type": "file_upload"},
            ]
        )
        fake_client.expect("GET", "/api/v1/assets/i_test/schema", ambiguous_schema)

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Attachments={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        assert "Attachments" in result.output
        assert "ff_x" in result.output
        assert "ff_y" in result.output
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)
        assert all(c[1] != "/api/v1/entries" for c in fake_client.calls)

    def test_non_file_field_fails_loud(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Resolving "Notes" → ff_n (a text field) must fail; we can't upload a
        # file into a text field. Caught before any S3 traffic.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"Notes={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        assert "Notes" in result.output
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)

    def test_record_task_values_failure_envelope_fails_loud(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # A 200 carrying {"success": false, "data": null} for the task values
        # must fail loud, not collapse to empty values and upload anyway.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect(
            "GET",
            "/api/v1/assets/r_789/schema",
            _evidence_schema(
                [{"key": "ff_s", "label": "Supporting Documents", "type": "file_upload"}]
            ),
        )
        fake_client.expect(
            "GET",
            "/api/v1/tasks/t_321",
            {
                "success": False,
                "data": None,
                "error": {"error_code": "TASK_NOT_FOUND", "message": "Task not found"},
            },
        )
        # No presign scripted: any further call fails the test.

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "r_789",
                "--task-id",
                "t_321",
                "--file",
                f"Supporting Documents={tmp_file}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        assert "Task not found" in result.output or "TASK_NOT_FOUND" in result.output
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


@patch("upscaler_cli.cli.helpers.make_client")
class TestDryRun:
    def test_dry_run_skips_network(
        self,
        mock_make_client,
        runner,
        fake_client,
        tmp_file,
    ):
        mock_make_client.return_value = fake_client

        result = runner.invoke(
            entry_group,
            [
                "update",
                "--entry-id",
                "i_test",
                "--file",
                f"ff_a={tmp_file}",
                "--dry-run",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        assert "dry-run" in result.output.lower()
        assert fake_client.calls == []


# ---------------------------------------------------------------------------
# FR-012: mid-batch upload failure triggers best-effort cleanup
# ---------------------------------------------------------------------------


@patch("upscaler_cli.cli.helpers.make_client")
class TestMidBatchUploadFailure:
    def test_cleanup_called_when_second_upload_fails(
        self,
        mock_make_client,
        runner,
        fake_client,
        tmp_path,
    ):
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "a.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "b.pdf"
        f2.write_bytes(b"BBB")

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_a"))
        fake_client.expect("POST", "/api/v1/files/presign", Exception("S3 unreachable"))
        # Cleanup call for the one landed uid.
        fake_client.expect("POST", "/api/v1/files/delete", {"success": True})

        with patch("upscaler_cli.uploads.httpx.AsyncClient") as mock_httpx_factory:
            _setup_s3_ok(mock_httpx_factory)

            result = runner.invoke(
                entry_group,
                [
                    "update",
                    "--entry-id",
                    "i_test",
                    "--file",
                    f"Evidence={f1}",
                    "--file",
                    f"Photos={f2}",
                ],
                obj=_make_ctx(),
            )

        assert result.exit_code != 0
        # No /api/v1/entries call was made.
        assert all(c[1] != "/api/v1/entries" for c in fake_client.calls)
        # The cleanup delete WAS made for the landed uid.
        deletes = [c for c in fake_client.calls if c[1] == "/api/v1/files/delete"]
        assert len(deletes) == 1
        assert deletes[0][2]["json"]["uid"] == "u_a"


# ---------------------------------------------------------------------------
# FR-014: conflict retry on ITEM_VERSION_CONFLICT (Items only)
# ---------------------------------------------------------------------------


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestConflictRetry:
    def test_retry_succeeds_on_second_attempt(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        # Story 1.9: two agents append to ff_a concurrently. Loser receives
        # ITEM_VERSION_CONFLICT, re-reads, re-appends (idempotent on uid),
        # retries with the refreshed version → final values has both uids.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}, version="v1"))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_x"))
        fake_client.expect(
            "POST",
            "/api/v1/entries",
            {"success": False, "error": "ITEM_VERSION_CONFLICT", "data": None},
        )
        # Refresh: the OTHER writer landed evidence-other.pdf at version v2.
        other_existing = [
            {
                "uid": "u_other",
                "name": "evidence-other.pdf",
                "type": "application/pdf",
                "size": 100,
                "addedAt": "2026-05-26T00:00:00+00:00",
            },
        ]
        fake_client.expect(
            "GET",
            "/api/v1/assets/i_test",
            _entry_envelope({"ff_a": other_existing}, version="v2"),
        )
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"ff_a={tmp_file}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        entries_calls = [c for c in fake_client.calls if c[1] == "/api/v1/entries"]
        assert len(entries_calls) == 2
        # Second attempt used refreshed version + merged both uids.
        body2 = entries_calls[1][2]["json"]
        assert body2["data"]["expectedVersion"] == "v2"
        uids = [item["uid"] for item in body2["data"]["values"]["ff_a"]]
        assert uids == ["u_other", "u_x"]

    def test_retry_exhaustion_emits_structured_error(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}, version="v1"))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_y"))
        for v in ("v1", "v2", "v3"):
            fake_client.expect(
                "POST",
                "/api/v1/entries",
                {"success": False, "error": "ITEM_VERSION_CONFLICT", "data": None},
            )
            if v != "v3":
                fake_client.expect(
                    "GET",
                    "/api/v1/assets/i_test",
                    _entry_envelope({}, version=v),
                )

        result = runner.invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--file", f"ff_a={tmp_file}"],
            obj=_make_ctx(json_mode=True),
        )

        assert result.exit_code != 0
        json_lines = [
            line for line in result.output.splitlines() if "ITEM_VERSION_CONFLICT" in line
        ]
        assert json_lines, result.output
        body = json.loads(json_lines[-1])
        assert body["error"] == "ITEM_VERSION_CONFLICT"
        assert body["orphan_uids"] == ["u_y"]


# ---------------------------------------------------------------------------
# upload-file sugar (one-shot single-file path)
# ---------------------------------------------------------------------------


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestEntryUploadFile:
    def test_upload_file_subcommand_resolves_title_and_succeeds(
        self,
        mock_make_client,
        mock_httpx_factory,
        runner,
        fake_client,
        tmp_file,
    ):
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        fake_client.expect("GET", "/api/v1/assets/i_test/schema", _evidence_schema())
        fake_client.expect("GET", "/api/v1/assets/i_test", _entry_envelope({}))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope())
        fake_client.expect("POST", "/api/v1/entries", _entries_success())

        result = runner.invoke(
            entry_group,
            [
                "upload-file",
                "--entry-id",
                "i_test",
                "--field",
                "Evidence",
                "--path",
                str(tmp_file),
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output


class TestSchemaFetchTaskScoping:
    """`?taskId=` must only be added for record ids, matching where the values
    actually switch to the task source (`_fetch_entry_values`). Appending it
    for a non-record item diverges schema from values."""

    @staticmethod
    def _client():
        from unittest.mock import AsyncMock, MagicMock

        client = MagicMock()
        client.request = AsyncMock(
            return_value={"success": True, "data": {"fields": []}}
        )
        return client

    def test_record_id_carries_task_id(self):
        from upscaler_cli.cli.entry import _fetch_schema_or_die

        client = self._client()
        _fetch_schema_or_die(_make_ctx(), client, "r_789", task_id="t_321")
        path = client.request.call_args[0][1]
        assert "taskId=t_321" in path

    def test_non_record_item_omits_task_id(self):
        from upscaler_cli.cli.entry import _fetch_schema_or_die

        client = self._client()
        _fetch_schema_or_die(_make_ctx(), client, "i_123", task_id="t_321")
        path = client.request.call_args[0][1]
        assert "taskId" not in path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(json_mode=False):
    from upscaler_cli.cli.context import Context

    c = Context()
    c.json_mode = json_mode
    c.verbose = False
    c.server_url = "https://test"
    c.profile = "test"
    return c
