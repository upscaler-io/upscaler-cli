"""Cross-package contract: agent-schema type strings.

These tests lock the wire string the backend emits for file-upload fields
(``packages/backend/src/shared/service/asset/blocks/form-upload.js``) against
the constant the SDK filters on. The backend side is locked by
``packages/backend/src/shared/service/asset/blocks/form-upload.test.js``;
both tests must agree.

Why this test exists: the original slice shipped with the CLI filtering on
``"form-upload"`` while the backend has always emitted ``"file_upload"``.
Tests on either side never crossed the boundary, so the drift went undetected
until a smoke test. This file is that boundary check.
"""

from upscaler_cli.cli.entry import AGENT_SCHEMA_FILE_UPLOAD_TYPE


def test_agent_schema_file_upload_type_matches_backend_emission():
    # The backend's toAgentSchema (form-upload.js) emits this literal.
    # If you change either side, change both, and update A050:936.
    assert AGENT_SCHEMA_FILE_UPLOAD_TYPE == "file_upload"
