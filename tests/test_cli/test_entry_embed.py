"""`upscaler entry update --embed FIELD=PATH`: upload a file and append its
markdown reference to a markdown text field."""

import json
from unittest.mock import patch

from click.testing import CliRunner

from tests.test_cli.test_entry_upload import (
    FakeUpscalerClient,
    _entries_success,
    _make_ctx,
    _presign_envelope,
    _schema_response,
    _setup_s3_ok,
)
from upscaler_cli.cli.entry import entry_group

_NOTE = {"key": "ff_note", "label": "Note", "type": "textarea", "format": "markdown"}
_TITLE = {"key": "ff_title", "label": "Title", "type": "text"}


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestEntryUpdateEmbed:
    def test_appends_image_markdown_to_the_stored_text(
        self, mock_make_client, mock_httpx, tmp_path
    ):
        _setup_s3_ok(mock_httpx)
        client = FakeUpscalerClient()
        mock_make_client.return_value = client
        image = tmp_path / "shot.png"
        image.write_bytes(b"png")
        client.expect("GET", "/api/v1/assets/i_test/schema", _schema_response([_TITLE, _NOTE]))
        # Current servers wrap the overview in `json` (up-ai 513fa5dfa).
        client.expect(
            "GET",
            "/api/v1/assets/i_test",
            {"success": True, "data": {"json": {"id": "i_test", "values": {"ff_note": "Intro"}}}},
        )
        client.expect("POST", "/api/v1/files/presign", _presign_envelope("i_test/abc"))
        client.expect("POST", "/api/v1/entries", _entries_success())

        result = CliRunner().invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--embed", f" note ={image}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        presign = next(c for c in client.calls if c[1] == "/api/v1/files/presign")
        assert presign[2]["json"]["asset_id"] == "i_test"
        assert "ref_id" not in presign[2]["json"]
        body = next(c for c in client.calls if c[1] == "/api/v1/entries")[2]["json"]
        assert body["data"]["values"] == {
            "ff_note": "Intro\n\n![shot.png](upscaler-file://i_test/abc/shot.png)"
        }

    def test_record_task_owns_the_upload(self, mock_make_client, mock_httpx, tmp_path):
        _setup_s3_ok(mock_httpx)
        client = FakeUpscalerClient()
        mock_make_client.return_value = client
        doc = tmp_path / "report.pdf"
        doc.write_bytes(b"%PDF")
        client.expect("GET", "/api/v1/assets/r_1/schema", _schema_response([_NOTE]))
        client.expect("GET", "/api/v1/tasks/t_1", {"success": True, "data": {"values": {}}})
        client.expect("POST", "/api/v1/files/presign", _presign_envelope("t_1/abc"))
        client.expect("POST", "/api/v1/entries", _entries_success())

        result = CliRunner().invoke(
            entry_group,
            ["update", "--entry-id", "r_1", "--task-id", "t_1", "--embed", f"Note={doc}"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        presign = next(c for c in client.calls if c[1] == "/api/v1/files/presign")
        assert presign[2]["json"]["ref_id"] == "t_1"
        body = next(c for c in client.calls if c[1] == "/api/v1/entries")[2]["json"]
        assert body["data"]["values"]["ff_note"] == (
            "[report.pdf](upscaler-file://t_1/abc/report.pdf)"
        )

    def test_non_markdown_field_fails_before_upload_with_json_error(
        self, mock_make_client, mock_httpx, tmp_path
    ):
        client = FakeUpscalerClient()
        mock_make_client.return_value = client
        image = tmp_path / "shot.png"
        image.write_bytes(b"png")
        client.expect("GET", "/api/v1/assets/i_test/schema", _schema_response([_TITLE, _NOTE]))

        result = CliRunner().invoke(
            entry_group,
            ["update", "--entry-id", "i_test", "--embed", f"Title={image}"],
            obj=_make_ctx(json_mode=True),
        )

        assert result.exit_code == 1
        error = json.loads(result.stderr)
        assert "Markdown text fields: Note" in error["error"]
        assert all(c[1] != "/api/v1/files/presign" for c in client.calls)
