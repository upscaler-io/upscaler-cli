"""Tests for upscaler_cli.auth.encryption module."""

from unittest.mock import patch

import pytest

from upscaler_cli.auth.encryption import decrypt, derive_key, encrypt


@pytest.fixture
def salt():
    """Provide a fixed 16-byte salt for deterministic tests."""
    return b"\x00" * 16


@pytest.fixture
def alt_salt():
    """Provide an alternative salt."""
    return b"\xff" * 16


@pytest.fixture
def key(salt):
    """Derive a key using the fixed salt."""
    return derive_key(salt)


# ---- derive_key ----


def test_derive_key_deterministic(salt):
    """Same salt produces the same key on repeated calls."""
    key_a = derive_key(salt)
    key_b = derive_key(salt)
    assert key_a == key_b


def test_derive_key_different_salt(salt, alt_salt):
    """Different salts produce different keys."""
    key_a = derive_key(salt)
    key_b = derive_key(alt_salt)
    assert key_a != key_b


# ---- encrypt / decrypt roundtrip ----


def test_encrypt_decrypt_roundtrip(key):
    """Encrypting then decrypting returns the original plaintext."""
    plaintext = "hello world"
    ciphertext = encrypt(plaintext, key)
    result = decrypt(ciphertext, key)
    assert result == plaintext


# ---- type checks ----


def test_encrypt_returns_bytes(key):
    """encrypt() returns bytes."""
    result = encrypt("data", key)
    assert isinstance(result, bytes)


def test_decrypt_returns_str(key):
    """decrypt() returns str."""
    ciphertext = encrypt("data", key)
    result = decrypt(ciphertext, key)
    assert isinstance(result, str)


# ---- failure cases ----


def test_decrypt_wrong_key_fails(salt, alt_salt):
    """Decrypting with a different key raises RuntimeError."""
    key_a = derive_key(salt)
    key_b = derive_key(alt_salt)
    ciphertext = encrypt("secret", key_a)
    with pytest.raises(RuntimeError, match="corrupted or copied"):
        decrypt(ciphertext, key_b)


def test_decrypt_corrupted_data_fails(key):
    """Corrupted ciphertext raises RuntimeError."""
    ciphertext = encrypt("secret", key)
    corrupted = ciphertext[:-4] + b"XXXX"
    with pytest.raises(RuntimeError, match="corrupted or copied"):
        decrypt(corrupted, key)


def test_cross_machine_failure(salt):
    """Key derived on a different machine cannot decrypt data from this machine."""
    key_original = derive_key(salt)
    ciphertext = encrypt("cross-machine-test", key_original)

    with patch(
        "upscaler_cli.auth.encryption._get_machine_identity",
        return_value="other-host:other-user",
    ):
        key_other = derive_key(salt)

    assert key_original != key_other
    with pytest.raises(RuntimeError, match="corrupted or copied"):
        decrypt(ciphertext, key_other)
