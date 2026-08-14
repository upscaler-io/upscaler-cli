"""Integration test: read commands end-to-end against live staging.

Requires a running REST API and a logged-in profile. Gated by
UPSCALER_INTEGRATION_TEST=1; skips unless authenticated and pointed at staging.
Read-only and non-destructive.

    UPSCALER_INTEGRATION_TEST=1 pytest tests/test_integration/test_read_flow.py -v

Flow: list definitions -> get first definition -> hierarchy; plus list todos
(the original silent-empty bug command) and search.
"""

import json
import os

import pytest

from tests.test_integration.conftest import invoke, list_items

pytestmark = pytest.mark.skipif(
    os.environ.get("UPSCALER_INTEGRATION_TEST") != "1",
    reason="Integration tests require UPSCALER_INTEGRATION_TEST=1",
)


class TestReadFlowIntegration:
    def test_list_todos_returns_success_envelope(self, runner, profile, require_auth):
        """The original bug command: a live `list todos` must return a
        success:true envelope (results or a legitimately empty list), never a
        swallowed failure."""
        result = invoke(runner, profile, "list", "todos")
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Proves the contract our envelope guard relies on: real reads carry an
        # explicit success flag, and the happy path is success:true.
        assert data.get("success") is True
        assert isinstance(data.get("data", []), (list, dict))

    def test_list_definitions(self, runner, profile, require_auth):
        result = invoke(runner, profile, "list", "definitions")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data.get("success") is True
        # `data` is a paginated dict ({"items": [...], "total": N}) or a list.
        assert isinstance(list_items(data.get("data")), list)

    def test_search_runs(self, runner, profile, require_auth):
        result = invoke(runner, profile, "search", "policy", "--limit", "3")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data.get("success") is True

    def test_list_then_get_then_hierarchy(self, runner, profile, require_auth):
        """Chain: list definitions -> get the first -> hierarchy of the same id."""
        listed = invoke(runner, profile, "list", "definitions")
        assert listed.exit_code == 0
        items = list_items(json.loads(listed.output).get("data"))
        if not items:
            pytest.skip("No definitions on this org to drill into.")

        first_id = items[0].get("id")
        assert first_id, f"definition has no id: {items[0]!r}"

        got = invoke(runner, profile, "get", first_id)
        assert got.exit_code == 0
        assert json.loads(got.output).get("success") is True

        tree = invoke(runner, profile, "hierarchy", first_id)
        assert tree.exit_code == 0
        assert json.loads(tree.output).get("success") is True
