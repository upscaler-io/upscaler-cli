"""End-to-end tests for the credential boundaries the CLI must not cross.

These cover the paths an attacker actually reaches: redirecting the CLI at a
server of their choosing, and credentials outliving `upscaler logout`.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from upscaler_cli.auth.token_store import TokenData, TokenStore
from upscaler_cli.client import UpscalerClient
from upscaler_cli.errors import AuthRequiredError

ISSUER = "https://ai.upscaler.app"


def _token(token_endpoint=f"{ISSUER}/mcp/token"):
    return TokenData(
        access_token="SECRET-ACCESS-TOKEN",
        refresh_token="SECRET-REFRESH-TOKEN",
        expires_at=time.time() + 86400,
        client_id="cid",
        client_secret="csecret",
        organization_id="org_1",
        token_endpoint=token_endpoint,
    )


def _store(token_data):
    store = MagicMock(spec=TokenStore)
    store.load.return_value = token_data
    return store


class TestTokenOriginBinding:
    """The stored token goes to the server that issued it, and nowhere else."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hostile_server",
        [
            "http://attacker.example",        # plaintext exfiltration
            "https://attacker.example",       # TLS does not make it ours
            "https://ai.upscaler.app.evil.test",  # suffix lookalike
            "https://ai.upscaler.app:8443",   # same host, different port
        ],
    )
    async def test_token_is_not_sent_to_another_origin(self, hostile_server):
        client = UpscalerClient(hostile_server, _store(_token()))

        with patch("httpx.AsyncClient") as mock_client:
            with pytest.raises(AuthRequiredError) as exc:
                await client.request("GET", "/api/v1/list")
            # The decisive assertion: no HTTP call was even attempted.
            mock_client.assert_not_called()

        assert "Refusing to send credentials" in str(exc.value)
        assert "SECRET-ACCESS-TOKEN" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_token_is_sent_to_its_own_issuer(self):
        client = UpscalerClient(ISSUER, _store(_token()))
        response = MagicMock(status_code=200, content=b"{}")
        response.json.return_value = {"success": True}

        inner = AsyncMock()
        inner.request.return_value = response
        inner.__aenter__ = AsyncMock(return_value=inner)
        inner.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=inner):
            await client.request("GET", "/api/v1/list")

        headers = inner.request.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer SECRET-ACCESS-TOKEN"

    @pytest.mark.asyncio
    async def test_trailing_slash_and_case_do_not_break_a_valid_session(self):
        client = UpscalerClient("https://AI.Upscaler.App/", _store(_token()))
        response = MagicMock(status_code=200, content=b"{}")
        response.json.return_value = {"success": True}
        inner = AsyncMock()
        inner.request.return_value = response
        inner.__aenter__ = AsyncMock(return_value=inner)
        inner.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=inner):
            await client.request("GET", "/api/v1/list")  # must not raise

    @pytest.mark.asyncio
    async def test_legacy_token_without_issuer_is_still_usable(self):
        """A token written before this field existed must not lock the user out."""
        client = UpscalerClient(ISSUER, _store(_token(token_endpoint="")))
        response = MagicMock(status_code=200, content=b"{}")
        response.json.return_value = {"success": True}
        inner = AsyncMock()
        inner.request.return_value = response
        inner.__aenter__ = AsyncMock(return_value=inner)
        inner.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=inner):
            await client.request("GET", "/api/v1/list")


class TestRequestPathInjection:
    @pytest.mark.asyncio
    async def test_traversing_id_never_reaches_the_network(self):
        client = UpscalerClient(ISSUER, _store(_token()))
        with patch("httpx.AsyncClient") as mock_client:
            with pytest.raises(Exception):
                await client.request(
                    "POST", "/api/v1/assets/d_x/../../../api/v1/admin/wipe/recover"
                )
            mock_client.assert_not_called()


class TestLogoutClearsEverything:
    def test_logout_revokes_refresh_token_as_well(self):
        """Revoking only the access token can leave a redeemable refresh token."""
        import asyncio

        from upscaler_cli.auth.oauth import OAuthFlow

        posted = []
        inner = AsyncMock()

        async def record(url, data=None, **kwargs):
            posted.append(data)
            return MagicMock(status_code=200)

        inner.post = record
        inner.__aenter__ = AsyncMock(return_value=inner)
        inner.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=inner):
            asyncio.run(OAuthFlow(ISSUER).revoke(_token()))

        sent = {(p["token"], p.get("token_type_hint")) for p in posted}
        assert ("SECRET-ACCESS-TOKEN", "access_token") in sent
        assert ("SECRET-REFRESH-TOKEN", "refresh_token") in sent

    def test_logout_removes_pending_device_code(self, tmp_path, monkeypatch):
        """An unredeemed device code is a live credential; logout must clear it."""
        from click.testing import CliRunner

        from upscaler_cli.cli.auth import _get_pending_path, _save_pending_device
        from upscaler_cli.cli.main import cli

        monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
        TokenStore(profile="prod").save(_token())
        _save_pending_device(
            {
                "device_code": "SECRET-DEVICE-CODE",
                "user_code": "ABCD-EFGH",
                "verification_uri": f"{ISSUER}/device",
                "expires_at": time.time() + 600,
                "server_url": ISSUER,
            },
            "prod",
        )
        pending = _get_pending_path("prod")

        with patch("upscaler_cli.auth.oauth.OAuthFlow.revoke", new=AsyncMock()):
            result = CliRunner().invoke(cli, ["logout"])

        assert result.exit_code == 0
        import os

        assert not os.path.exists(pending)

    def test_logout_clears_pending_code_even_with_no_tokens(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from upscaler_cli.cli.auth import _get_pending_path, _save_pending_device
        from upscaler_cli.cli.main import cli

        monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home2"))
        _save_pending_device(
            {"device_code": "SECRET", "expires_at": time.time() + 600}, "prod"
        )
        pending = _get_pending_path("prod")

        result = CliRunner().invoke(cli, ["logout"])

        assert result.exit_code == 0
        import os

        assert not os.path.exists(pending)


class TestInsecureTransportWarning:
    def test_plaintext_http_warns_on_stderr(self, capsys):
        from upscaler_cli.cli import helpers

        helpers._INSECURE_WARNED.clear()
        helpers.warn_if_insecure_transport("http://10.0.0.5:8080", True)
        assert "plaintext HTTP" in capsys.readouterr().err

    def test_disabled_verification_warns(self, capsys):
        from upscaler_cli.cli import helpers

        helpers._INSECURE_WARNED.clear()
        helpers.warn_if_insecure_transport("https://self-signed.internal", False)
        assert "certificate verification is disabled" in capsys.readouterr().err

    def test_normal_https_is_silent(self, capsys):
        from upscaler_cli.cli import helpers

        helpers._INSECURE_WARNED.clear()
        helpers.warn_if_insecure_transport(ISSUER, True)
        assert capsys.readouterr().err == ""

    def test_warning_is_not_repeated(self, capsys):
        from upscaler_cli.cli import helpers

        helpers._INSECURE_WARNED.clear()
        helpers.warn_if_insecure_transport("http://x.test", True)
        capsys.readouterr()
        helpers.warn_if_insecure_transport("http://x.test", True)
        assert capsys.readouterr().err == ""


class TestTokenStoreOnDisk:
    def test_saved_credentials_are_owner_only(self, tmp_path, monkeypatch):
        import os
        import stat

        monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
        # umask is process-global; restore it so test order stays irrelevant.
        previous_umask = os.umask(0o022)
        try:
            store = TokenStore(profile="prod")
            store.save(_token())
        finally:
            os.umask(previous_umask)

        for name in (".salt", "tokens.enc"):
            path = store.config_dir / name
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, name

    def test_round_trip_still_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
        store = TokenStore(profile="prod")
        store.save(_token())
        loaded = store.load()
        assert loaded.access_token == "SECRET-ACCESS-TOKEN"
        assert json.loads(json.dumps(loaded.__dict__))["organization_id"] == "org_1"
