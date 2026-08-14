"""Tests for upscaler_cli.auth.token_store module."""

import os

import pytest

from upscaler_cli.auth.token_store import TokenData, TokenStore

# ---- save / load roundtrip ----


def test_save_load_roundtrip(tmp_config_dir, sample_token_data):
    """Saving then loading returns identical TokenData."""
    store = TokenStore(config_dir=str(tmp_config_dir))
    original = TokenData(**sample_token_data)

    store.save(original)
    loaded = store.load()

    assert loaded.access_token == original.access_token
    assert loaded.refresh_token == original.refresh_token
    assert loaded.expires_at == original.expires_at
    assert loaded.client_id == original.client_id
    assert loaded.client_secret == original.client_secret
    assert loaded.organization_id == original.organization_id
    assert loaded.token_endpoint == original.token_endpoint


# ---- file permissions ----


def test_file_permissions(tmp_path, sample_token_data):
    """Config dir is 0o700, token and salt files are 0o600."""
    config_dir = tmp_path / "fresh_config"
    store = TokenStore(config_dir=str(config_dir))
    store.save(TokenData(**sample_token_data))

    dir_mode = os.stat(config_dir).st_mode & 0o777
    assert dir_mode == 0o700

    salt_mode = os.stat(config_dir / ".salt").st_mode & 0o777
    assert salt_mode == 0o600

    token_mode = os.stat(config_dir / "tokens.enc").st_mode & 0o777
    assert token_mode == 0o600


def test_profile_dir_hierarchy_is_0o700(monkeypatch, tmp_path, sample_token_data):
    """~/.upscaler/ and ~/.upscaler/profiles/ are 0o700 after a fresh save.

    Path.mkdir(parents=True) honors umask for intermediate dirs; this test
    guards against a regression where the profiles/ dir leaks the profile
    list to other users on the system.
    """
    home = tmp_path / "home"
    monkeypatch.setenv("UPSCALER_HOME", str(home))
    TokenStore(profile="dev").save(TokenData(**sample_token_data))

    assert os.stat(home).st_mode & 0o777 == 0o700
    assert os.stat(home / "profiles").st_mode & 0o777 == 0o700
    assert os.stat(home / "profiles" / "dev").st_mode & 0o777 == 0o700


# ---- atomic write ----


def test_atomic_write(tmp_config_dir, sample_token_data):
    """Temporary file is cleaned up after save completes."""
    store = TokenStore(config_dir=str(tmp_config_dir))
    store.save(TokenData(**sample_token_data))

    tmp_file = tmp_config_dir / "tokens.enc.tmp"
    assert not tmp_file.exists()


# ---- load failure: missing file ----


def test_missing_file_raises(tmp_config_dir):
    """Loading without tokens.enc raises RuntimeError with 'Not logged in'."""
    store = TokenStore(config_dir=str(tmp_config_dir))

    with pytest.raises(RuntimeError, match="Not logged in"):
        store.load()


# ---- load failure: corrupted file ----


def test_corrupted_file_raises(tmp_config_dir):
    """Loading garbage token data raises RuntimeError with 'corrupted'."""
    store = TokenStore(config_dir=str(tmp_config_dir))

    # Create a salt file so we get past the salt check
    salt_path = tmp_config_dir / ".salt"
    salt_path.write_bytes(os.urandom(16))
    os.chmod(salt_path, 0o600)

    # Write garbage to tokens.enc
    token_path = tmp_config_dir / "tokens.enc"
    token_path.write_bytes(b"garbage data that is not valid fernet")

    with pytest.raises(RuntimeError, match="corrupted"):
        store.load()


# ---- delete ----


def test_delete_removes_files(tmp_config_dir, sample_token_data):
    """Delete removes salt and token files."""
    store = TokenStore(config_dir=str(tmp_config_dir))
    store.save(TokenData(**sample_token_data))

    assert (tmp_config_dir / "tokens.enc").exists()
    assert (tmp_config_dir / ".salt").exists()

    store.delete()

    assert not (tmp_config_dir / "tokens.enc").exists()
    assert not (tmp_config_dir / ".salt").exists()


# ---- is_expired ----


def test_is_expired_future(tmp_config_dir, sample_token_data):
    """Token with expires_at in the future is not expired."""
    store = TokenStore(config_dir=str(tmp_config_dir))
    store.save(TokenData(**sample_token_data))

    assert store.is_expired() is False


def test_is_expired_past(tmp_config_dir, expired_token_data):
    """Token with expires_at in the past is expired."""
    store = TokenStore(config_dir=str(tmp_config_dir))
    store.save(TokenData(**expired_token_data))

    assert store.is_expired() is True


def test_is_expired_no_file(tmp_config_dir):
    """No token file means token is expired."""
    store = TokenStore(config_dir=str(tmp_config_dir))

    assert store.is_expired() is True
