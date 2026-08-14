"""Integration test: todo write lifecycle end-to-end against live staging/dev.

DESTRUCTIVE: creates a todo on the live org, drives it through update/close/
reopen, then deletes it. Double-gated by UPSCALER_INTEGRATION_TEST=1 and the
non-prod host guard (see conftest), so it can never run against prod. A
best-effort delete runs in `finally`, so a failed assertion still removes the
created todo.

    UPSCALER_INTEGRATION_TEST=1 pytest tests/test_integration/test_write_flow.py -v

Note: `todo delete` is a soft delete — the row leaves `list todos` but `get
<id>` still resolves it. So deletion is asserted by its success envelope, not by
a post-delete `get`.
"""

import json
import os

import pytest

from tests.test_integration.conftest import invoke

pytestmark = pytest.mark.skipif(
    os.environ.get("UPSCALER_INTEGRATION_TEST") != "1",
    reason="Integration tests require UPSCALER_INTEGRATION_TEST=1",
)

# Marks the row as ours so a stray todo is identifiable if cleanup ever fails.
_TITLE = "up-sdk integration test todo (safe to delete)"


def _get_todo(runner, profile, todo_id):
    """Fetch a todo by id, returning its `data` dict (asserts the read works)."""
    res = invoke(runner, profile, "get", todo_id, "--type", "todo")
    assert res.exit_code == 0, res.output
    return json.loads(res.output).get("data") or {}


class TestWriteFlowIntegration:
    def test_todo_full_lifecycle(self, runner, profile, require_auth):
        """create -> read -> update -> close -> reopen -> delete, asserting the
        observable state after each transition."""
        created = invoke(runner, profile, "todo", "create", "--title", _TITLE)
        assert created.exit_code == 0, created.output
        payload = json.loads(created.output)
        assert payload.get("success") is True
        todo_id = (payload.get("data") or {}).get("id")
        assert todo_id, f"create returned no id: {payload!r}"

        deleted_in_test = False
        try:
            # read back: persisted with our title, status OPEN
            data = _get_todo(runner, profile, todo_id)
            assert data.get("title") == _TITLE
            assert data.get("status") == "OPEN"

            # update: title changes
            renamed = _TITLE + " (renamed)"
            upd = invoke(runner, profile, "todo", "update", todo_id, "--title", renamed)
            assert upd.exit_code == 0, upd.output
            assert json.loads(upd.output).get("success") is True
            assert _get_todo(runner, profile, todo_id).get("title") == renamed

            # close: status -> CLOSED
            closed = invoke(runner, profile, "todo", "close", todo_id)
            assert closed.exit_code == 0, closed.output
            assert _get_todo(runner, profile, todo_id).get("status") == "CLOSED"

            # reopen: status -> OPEN
            reopened = invoke(runner, profile, "todo", "reopen", todo_id)
            assert reopened.exit_code == 0, reopened.output
            assert _get_todo(runner, profile, todo_id).get("status") == "OPEN"

            # delete: success envelope (soft delete; not re-read here)
            deleted = invoke(runner, profile, "todo", "delete", todo_id)
            assert deleted.exit_code == 0, deleted.output
            assert json.loads(deleted.output).get("success") is True
            deleted_in_test = True
        finally:
            if not deleted_in_test:
                # Safety net: an earlier assertion failed before our delete ran.
                invoke(runner, profile, "todo", "delete", todo_id)
