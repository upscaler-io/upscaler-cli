"""Integration test: auth status + refresh against a live staging session.

Requires a running OAuth server and a logged-in profile. Gated by
UPSCALER_INTEGRATION_TEST=1; skips unless the profile is authenticated and
resolves to staging (see conftest). Read-only — never logs out the session it
borrows, so it is safe to run repeatedly.

    UPSCALER_INTEGRATION_TEST=1 upscaler --profile dev login   # one-time
    UPSCALER_INTEGRATION_TEST=1 pytest tests/test_integration/test_auth_flow.py -v
"""

import json
import os

import pytest

from tests.test_integration.conftest import invoke

pytestmark = pytest.mark.skipif(
    os.environ.get("UPSCALER_INTEGRATION_TEST") != "1",
    reason="Integration tests require UPSCALER_INTEGRATION_TEST=1",
)


class TestAuthFlowIntegration:
    def test_status_reports_org_and_refresh_token(self, runner, profile, require_auth):
        """A live session reports an org and a present refresh token (json)."""
        result = invoke(runner, profile, "status")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["authenticated"] is True
        assert data["expired"] is False
        # `organization_id` is the LOCAL copy and may be None even on a working
        # session — the server scopes from the JWT claim, not this field. So
        # assert the field is present (backs the human-mode line) and that a
        # refresh token exists, without requiring a populated org here.
        assert "organization_id" in data
        assert data["refresh_token_present"] is True

    def test_status_human_mode_shows_expiry_and_refresh_lines(
        self, runner, profile, require_auth
    ):
        """Human-mode status surfaces the expiry + refresh-token lines live."""
        result = invoke(runner, profile, "status", json_mode=False)
        assert result.exit_code == 0
        assert "Authenticated" in result.output
        assert "Expires in:" in result.output
        assert "Refresh token: present" in result.output

    def test_refresh_preserves_org(self, runner, profile, require_auth):
        """`refresh` keeps the org binding (end-to-end check of the refresh-org
        alignment fix): status before and after refresh must report the same
        organization_id."""
        org_before = require_auth["organization_id"]

        refreshed = invoke(runner, profile, "refresh")
        assert refreshed.exit_code == 0

        after = invoke(runner, profile, "status")
        assert after.exit_code == 0
        org_after = json.loads(after.output)["organization_id"]
        assert org_after == org_before
