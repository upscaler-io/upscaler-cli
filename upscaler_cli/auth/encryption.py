"""Token encryption using Fernet with machine-bound PBKDF2 key derivation.

Security model:
- Key derived from machine identity (hostname:username) + random salt
- PBKDF2-HMAC-SHA256 with 480,000 iterations
- Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256)
- Tokens encrypted at rest, decrypted in-memory only
- Different machine = different key = decryption fails
"""

import base64
import getpass
import platform

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _get_machine_identity() -> str:
    """Return machine-bound identity string: '{hostname}:{username}'."""
    hostname = platform.node()
    username = getpass.getuser()
    return f"{hostname}:{username}"


def derive_key(salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from machine identity and salt.

    Args:
        salt: Random bytes (16 bytes recommended) from ~/.upscaler/.salt

    Returns:
        32-byte key suitable for Fernet encryption.
    """
    identity = _get_machine_identity().encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    raw_key = kdf.derive(identity)
    return base64.urlsafe_b64encode(raw_key)


def encrypt(plaintext: str, key: bytes) -> bytes:
    """Encrypt a plaintext string using Fernet.

    Args:
        plaintext: String to encrypt (typically JSON-serialized token data).
        key: Fernet-compatible key from derive_key().

    Returns:
        Encrypted bytes (Fernet token).
    """
    fernet = Fernet(key)
    return fernet.encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes, key: bytes) -> str:
    """Decrypt Fernet-encrypted bytes back to plaintext string.

    Args:
        ciphertext: Encrypted bytes from encrypt().
        key: Same Fernet key used for encryption.

    Returns:
        Decrypted plaintext string.

    Raises:
        RuntimeError: If decryption fails (wrong key, corrupted data, or
            token copied from another machine).
    """
    fernet = Fernet(key)
    try:
        return fernet.decrypt(ciphertext).decode("utf-8")
    except InvalidToken:
        raise RuntimeError(
            "Token store corrupted or copied from another machine. "
            "Run: upscaler login"
        )
