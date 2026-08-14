"""Integration tests for `upscaler asset update-content --file` and `asset upload-file`.

Documents persist values as a Slate tree (Pattern A per ADR-008). The CLI must:
  1. Read the current Slate tree (or accept one via `--data`).
  2. Validate every `--file FIELD=PATH`'s FIELD matches an `options.name` on a
     file block in the tree BEFORE any S3 upload.
  3. Upload each file, splice into the matching block's `fileList`.
  4. Issue a SINGLE setDocumentDefinitionValues call (operation=update_content).
  5. NO `expectedVersion` is sent (Documents accept LWW in v1).
"""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from upscaler_cli.cli.asset import asset_group

# ---------------------------------------------------------------------------
# Test doubles (mirrors test_entry_upload.py)
# ---------------------------------------------------------------------------


class FakeUpscalerClient:
    """Scripted in-memory client. Pops responses on (method, path-prefix) match."""

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
        raise AssertionError(
            f"Unscripted call: {method} {path}. Remaining: {self.script}"
        )


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
# Slate fixtures
# ---------------------------------------------------------------------------


def _file_block(name, file_list=None):
    """Slate `type:"file"` block. children are preserved verbatim by the walker."""
    return {
        "type": "file",
        "options": {"name": name},
        "fileList": list(file_list or []),
        "children": [{"text": ""}],
    }


def _document_envelope(slate_tree, asset_id="d_abc"):
    """GET /api/v1/assets/{asset_id} response for a document.

    Documents return `values` as a Slate tree (a list of blocks).
    """
    return {
        "success": True,
        "data": {"id": asset_id, "values": slate_tree},
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


def _assets_success(asset_id="d_abc"):
    return {
        "success": True,
        "data": {"id": asset_id, "asset_id": asset_id},
        "error": None,
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
class TestAssetUploadFileHappyPaths:
    def test_upload_file_appends_to_named_block(
        self, mock_make_client, mock_httpx_factory, runner, fake_client, tmp_file,
    ):
        # Story 1.4: read current tree, splice the file item into the matching
        # block's fileList, persist via setDocumentDefinitionValues (op
        # update_content). NO expectedVersion (LWW per FR-013).
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        tree = [_file_block("attachments")]
        fake_client.expect("GET", "/api/v1/assets/d_abc", _document_envelope(tree))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_x"))
        fake_client.expect("POST", "/api/v1/assets", _assets_success())

        result = runner.invoke(
            asset_group,
            ["upload-file", "--asset-id", "d_abc", "--field", "attachments",
             "--path", str(tmp_file)],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        # One mutation call.
        mutation_calls = [c for c in fake_client.calls if c[1] == "/api/v1/assets"]
        assert len(mutation_calls) == 1
        body = mutation_calls[0][2]["json"]
        assert body["operation"] == "update_content"
        assert body["asset_id"] == "d_abc"
        # The spliced tree has the new uid on the attachments block.
        spliced = body["data"]["values"]
        assert spliced[0]["fileList"][0]["uid"] == "u_x"
        # LWW: no expectedVersion in payload.
        assert "expectedVersion" not in body["data"]

    def test_update_content_batches_multiple_files_into_one_mutation(
        self, mock_make_client, mock_httpx_factory, runner, fake_client, tmp_path,
    ):
        # Story 1.5: two --file pairs → two uploads, one mutation, both file
        # items spliced onto their respective blocks.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "report.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "architecture.png"
        f2.write_bytes(b"BBB")

        tree = [_file_block("attachments"), _file_block("diagrams")]
        fake_client.expect("GET", "/api/v1/assets/d_abc", _document_envelope(tree))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_a"))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_b"))
        fake_client.expect("POST", "/api/v1/assets", _assets_success())

        result = runner.invoke(
            asset_group,
            [
                "update-content", "--asset-id", "d_abc",
                "--file", f"attachments={f1}",
                "--file", f"diagrams={f2}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        mutation_calls = [c for c in fake_client.calls if c[1] == "/api/v1/assets"]
        assert len(mutation_calls) == 1
        spliced = mutation_calls[0][2]["json"]["data"]["values"]
        # attachments → u_a, diagrams → u_b.
        attachments_block = next(b for b in spliced if b["options"]["name"] == "attachments")
        diagrams_block = next(b for b in spliced if b["options"]["name"] == "diagrams")
        assert [item["uid"] for item in attachments_block["fileList"]] == ["u_a"]
        assert [item["uid"] for item in diagrams_block["fileList"]] == ["u_b"]

    def test_data_provides_baseline_tree_so_no_read_is_needed(
        self, mock_make_client, mock_httpx_factory, runner, fake_client, tmp_file,
    ):
        # When --data is supplied with `values`, that IS the baseline tree:
        # the SDK must NOT pre-read the current doc. File appends are spliced
        # into the supplied tree.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        baseline = [_file_block("attachments")]
        # NO GET expectation; the test will fail if the SDK reads the doc.
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_x"))
        fake_client.expect("POST", "/api/v1/assets", _assets_success())

        result = runner.invoke(
            asset_group,
            [
                "update-content", "--asset-id", "d_abc",
                "--data", json.dumps({"values": baseline}),
                "--file", f"attachments={tmp_file}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        # No GET on the document.
        assert all(not c[1].startswith("/api/v1/assets/d_abc") for c in fake_client.calls)
        call = next(c for c in fake_client.calls if c[1] == "/api/v1/assets")
        spliced = call[2]["json"]["data"]["values"]
        assert spliced[0]["fileList"][0]["uid"] == "u_x"

    def test_existing_files_on_block_are_preserved(
        self, mock_make_client, mock_httpx_factory, runner, fake_client, tmp_file,
    ):
        # Walker must append rather than replace: prior web-editor uploads
        # must survive a CLI append.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        existing = [
            {
                "uid": "u_pre", "name": "prior.pdf",
                "type": "application/pdf", "size": 100,
                "addedAt": "2026-05-01T00:00:00+00:00",
            },
        ]
        tree = [_file_block("attachments", existing)]
        fake_client.expect("GET", "/api/v1/assets/d_abc", _document_envelope(tree))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_new"))
        fake_client.expect("POST", "/api/v1/assets", _assets_success())

        result = runner.invoke(
            asset_group,
            ["upload-file", "--asset-id", "d_abc", "--field", "attachments",
             "--path", str(tmp_file)],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        call = next(c for c in fake_client.calls if c[1] == "/api/v1/assets")
        spliced = call[2]["json"]["data"]["values"]
        uids = [item["uid"] for item in spliced[0]["fileList"]]
        assert uids == ["u_pre", "u_new"]

    def test_children_preserved_verbatim(
        self, mock_make_client, mock_httpx_factory, runner, fake_client, tmp_file,
    ):
        # FR-006: "The file block's `children` are preserved verbatim; only
        # `fileList` is touched."
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        marker_children = [{"text": "DO NOT TOUCH THIS"}]
        tree = [{
            "type": "file",
            "options": {"name": "attachments"},
            "fileList": [],
            "children": marker_children,
        }]
        fake_client.expect("GET", "/api/v1/assets/d_abc", _document_envelope(tree))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_x"))
        fake_client.expect("POST", "/api/v1/assets", _assets_success())

        result = runner.invoke(
            asset_group,
            ["upload-file", "--asset-id", "d_abc", "--field", "attachments",
             "--path", str(tmp_file)],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        call = next(c for c in fake_client.calls if c[1] == "/api/v1/assets")
        spliced = call[2]["json"]["data"]["values"]
        assert spliced[0]["children"] == marker_children


# ---------------------------------------------------------------------------
# Fail-loud validation BEFORE any S3 upload
# ---------------------------------------------------------------------------


@patch("upscaler_cli.uploads.httpx.AsyncClient")
@patch("upscaler_cli.cli.helpers.make_client")
class TestAssetUploadValidation:
    def test_unknown_block_name_fails_loud_before_any_upload(
        self, mock_make_client, mock_httpx_factory, runner, fake_client, tmp_file,
    ):
        # Story 1.6 (Pattern A): typo'd field name → exit non-zero, list
        # available options.name values, NO presign call.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        tree = [_file_block("attachments"), _file_block("diagrams")]
        fake_client.expect("GET", "/api/v1/assets/d_abc", _document_envelope(tree))
        # No further calls scripted.

        result = runner.invoke(
            asset_group,
            ["upload-file", "--asset-id", "d_abc", "--field", "atatchments",
             "--path", str(tmp_file)],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        assert "atatchments" in result.output
        # Shows the available file-block names.
        assert "attachments" in result.output
        assert "diagrams" in result.output
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)
        # No mutation either.
        assert all(c[1] != "/api/v1/assets" for c in fake_client.calls)

    def test_validates_all_fields_before_any_upload(
        self, mock_make_client, mock_httpx_factory, runner, fake_client, tmp_path,
    ):
        # FR-006: "validate ALL field names exist before any S3 upload". When
        # the second --file is bogus, the FIRST must NOT be uploaded either.
        _setup_s3_ok(mock_httpx_factory)
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "ok.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "bad.pdf"
        f2.write_bytes(b"BBB")

        tree = [_file_block("attachments")]
        fake_client.expect("GET", "/api/v1/assets/d_abc", _document_envelope(tree))

        result = runner.invoke(
            asset_group,
            [
                "update-content", "--asset-id", "d_abc",
                "--file", f"attachments={f1}",
                "--file", f"nonexistent={f2}",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code != 0
        # The good upload was NOT triggered because the bad one was caught at
        # validation time.
        assert all(not c[1].startswith("/api/v1/files/presign") for c in fake_client.calls)
        assert all(c[1] != "/api/v1/assets" for c in fake_client.calls)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


@patch("upscaler_cli.cli.helpers.make_client")
class TestAssetUploadDryRun:
    def test_dry_run_skips_network(
        self, mock_make_client, runner, fake_client, tmp_file,
    ):
        mock_make_client.return_value = fake_client

        result = runner.invoke(
            asset_group,
            ["upload-file", "--asset-id", "d_abc", "--field", "attachments",
             "--path", str(tmp_file), "--dry-run"],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        assert "dry-run" in result.output.lower()
        assert fake_client.calls == []


# ---------------------------------------------------------------------------
# FR-012: mid-batch upload failure triggers best-effort cleanup
# ---------------------------------------------------------------------------


@patch("upscaler_cli.cli.helpers.make_client")
class TestAssetUploadMidBatchFailure:
    def test_cleanup_called_when_second_upload_fails(
        self, mock_make_client, runner, fake_client, tmp_path,
    ):
        mock_make_client.return_value = fake_client

        f1 = tmp_path / "a.pdf"
        f1.write_bytes(b"AAA")
        f2 = tmp_path / "b.pdf"
        f2.write_bytes(b"BBB")

        tree = [_file_block("attachments"), _file_block("diagrams")]
        fake_client.expect("GET", "/api/v1/assets/d_abc", _document_envelope(tree))
        fake_client.expect("POST", "/api/v1/files/presign", _presign_envelope("u_a"))
        fake_client.expect("POST", "/api/v1/files/presign", Exception("S3 unreachable"))
        fake_client.expect("POST", "/api/v1/files/delete", {"success": True})

        with patch("upscaler_cli.uploads.httpx.AsyncClient") as mock_httpx_factory:
            _setup_s3_ok(mock_httpx_factory)

            result = runner.invoke(
                asset_group,
                [
                    "update-content", "--asset-id", "d_abc",
                    "--file", f"attachments={f1}",
                    "--file", f"diagrams={f2}",
                ],
                obj=_make_ctx(),
            )

        assert result.exit_code != 0
        # No mutation call landed.
        assert all(c[1] != "/api/v1/assets" for c in fake_client.calls)
        # Cleanup ran for the landed uid.
        deletes = [c for c in fake_client.calls if c[1] == "/api/v1/files/delete"]
        assert len(deletes) == 1
        assert deletes[0][2]["json"]["uid"] == "u_a"


# ---------------------------------------------------------------------------
# update-content without --file still works (backwards-compat for slice 7)
# ---------------------------------------------------------------------------


@patch("upscaler_cli.cli.helpers.make_client")
class TestAssetUpdateContentNoFiles:
    def test_data_only_update_content_unchanged(
        self, mock_make_client, runner, fake_client,
    ):
        # The existing --data-only path must still call /api/v1/assets with
        # operation=update_content. Slice 7 must not regress this.
        mock_make_client.return_value = fake_client

        fake_client.expect("POST", "/api/v1/assets", _assets_success())

        result = runner.invoke(
            asset_group,
            [
                "update-content", "--asset-id", "d_abc",
                "--data", '{"values": "# Hello"}',
                "--values-type", "markdown",
            ],
            obj=_make_ctx(),
        )

        assert result.exit_code == 0, result.output
        body = fake_client.calls[0][2]["json"]
        assert body["operation"] == "update_content"
        assert body["asset_id"] == "d_abc"
        assert body["data"]["values"] == "# Hello"


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
