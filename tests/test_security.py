"""Regression tests for the security hardening in upscaler_cli.security.

Each test pins a behaviour that a real attack depended on before the fix:
credentials crossing an origin boundary, an id escaping its path segment, or a
secret landing on disk at the ambient umask.
"""

import os
import stat
from pathlib import Path

import pytest

from upscaler_cli.errors import CLIError
from upscaler_cli.security import (
    ensure_private_dir,
    origin_of,
    same_origin,
    validate_id,
    validate_request_path,
    write_private_bytes,
    write_private_text,
)


class TestOrigin:
    def test_default_port_is_implied(self):
        assert same_origin("https://api.example.com", "https://api.example.com:443/mcp/token")
        assert same_origin("http://localhost:80/x", "http://localhost/y")

    def test_host_comparison_is_case_insensitive(self):
        assert same_origin("https://API.Example.COM", "https://api.example.com/mcp/token")

    @pytest.mark.parametrize(
        "a,b",
        [
            ("https://api.example.com", "https://evil.example.com"),
            ("https://api.example.com", "http://api.example.com"),
            ("https://api.example.com", "https://api.example.com:8443"),
            # Suffix games must not pass: attacker registers the longer name.
            ("https://api.example.com", "https://api.example.com.evil.test"),
        ],
    )
    def test_distinct_origins_do_not_match(self, a, b):
        assert not same_origin(a, b)

    def test_unusable_values_never_match(self):
        assert not same_origin("", "https://api.example.com")
        assert not same_origin("https://api.example.com", "")
        assert not same_origin("not a url", "not a url")
        assert origin_of("") is None
        assert origin_of("https://h:notaport") is None


class TestRequestPathValidation:
    def test_ordinary_paths_pass_through(self):
        assert validate_request_path("/api/v1/assets/d_abc123") == "/api/v1/assets/d_abc123"

    def test_traversal_is_rejected(self):
        # httpx resolves `..` when it parses the URL, which would send the
        # request (and the bearer token) to an endpoint the command never named.
        with pytest.raises(CLIError):
            validate_request_path("/api/v1/assets/d_x/../../../admin/takeover/recover")

    def test_query_and_fragment_are_rejected(self):
        with pytest.raises(CLIError):
            validate_request_path("/api/v1/assets/d_x?admin=1")
        with pytest.raises(CLIError):
            validate_request_path("/api/v1/assets/d_x#frag")

    def test_empty_segment_and_relative_path_rejected(self):
        with pytest.raises(CLIError):
            validate_request_path("/api/v1//assets")
        with pytest.raises(CLIError):
            validate_request_path("api/v1/assets")

    def test_control_characters_rejected(self):
        with pytest.raises(CLIError):
            validate_request_path("/api/v1/assets/d_x\r\nX-Injected: 1")


class TestIdValidation:
    def test_opaque_ids_are_accepted(self):
        for value in ("d_abc123", "rg_ABC-123", "to_x.y", "9xKq2LmN0pQr"):
            assert validate_id(value) == value

    @pytest.mark.parametrize(
        "value", ["d_x/../y", "d_x?a=1", "d_x#f", "d_x%2f", "d_ x", "d_x\ty", ""]
    )
    def test_structural_characters_are_rejected(self, value):
        with pytest.raises(CLIError):
            validate_id(value)


@pytest.fixture
def permissive_umask():
    """Run the test under umask 0o022 — the value that used to leak through
    write-then-chmod — and restore the caller's umask afterwards.

    umask is process-global, so leaving it modified would make unrelated tests
    order-dependent.
    """
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


class TestPrivateFileWrites:
    def test_file_is_never_wider_than_0600(self, tmp_path, permissive_umask):
        target = tmp_path / "secret.bin"
        write_private_bytes(target, b"token")
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600
        assert not mode & stat.S_IRGRP
        assert not mode & stat.S_IROTH

    def test_chmod_is_not_used_after_the_write(self, tmp_path, monkeypatch):
        """The mode must come from open(), so there is no widened window."""
        calls = []
        real_chmod = os.chmod
        monkeypatch.setattr(
            os, "chmod", lambda p, m: (calls.append((str(p), m)), real_chmod(p, m))[1]
        )
        write_private_bytes(tmp_path / "s.bin", b"x")
        assert calls == []

    def test_existing_wide_file_is_repaired(self, tmp_path):
        target = tmp_path / "legacy.enc"
        target.write_bytes(b"old")
        os.chmod(target, 0o644)
        write_private_bytes(target, b"new")
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert target.read_bytes() == b"new"

    @pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="needs O_NOFOLLOW")
    def test_symlink_at_destination_is_refused(self, tmp_path):
        victim = tmp_path / "victim"
        link = tmp_path / "link"
        link.symlink_to(victim)
        with pytest.raises(OSError):
            write_private_bytes(link, b"payload")
        assert not victim.exists()

    def test_text_helper_round_trips(self, tmp_path):
        target = tmp_path / "t.txt"
        write_private_text(target, "héllo")
        assert target.read_text(encoding="utf-8") == "héllo"
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


class TestPrivateDir:
    def test_created_dir_is_0700(self, tmp_path):
        target = tmp_path / "a" / "b"
        ensure_private_dir(target)
        assert stat.S_IMODE(target.stat().st_mode) == 0o700

    def test_existing_loose_dir_is_tightened(self, tmp_path):
        """mkdir(exist_ok=True) leaves an existing dir alone; this must not."""
        target = tmp_path / "loose"
        target.mkdir()
        os.chmod(target, 0o755)
        ensure_private_dir(target)
        assert stat.S_IMODE(target.stat().st_mode) == 0o700


class TestProfileDirPermissions:
    def test_ensure_profile_dir_tightens_whole_tree(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
        from upscaler_cli.profile import ensure_profile_dir, profiles_root, upscaler_home

        home = upscaler_home()
        home.mkdir(parents=True)
        os.chmod(home, 0o755)
        root = profiles_root()
        root.mkdir()
        os.chmod(root, 0o755)

        ensure_profile_dir(root / "prod")

        for d in (home, root, root / "prod"):
            assert stat.S_IMODE(Path(d).stat().st_mode) == 0o700, d
