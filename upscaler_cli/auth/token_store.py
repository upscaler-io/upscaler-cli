"""Encrypted token persistence with atomic writes.

Stores OAuth tokens encrypted at rest using Fernet with a machine-bound key.
File layout:
    ~/.upscaler/
    |- .salt        # 16 random bytes for key derivation (mode 0o600)
    +- tokens.enc   # Fernet-encrypted JSON token data (mode 0o600)
"""

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from upscaler_cli.auth.encryption import decrypt, derive_key, encrypt
from upscaler_cli.profile import ensure_profile_dir, get_profile_dir


@dataclass
class TokenData:
    """OAuth token data stored encrypted on disk."""

    access_token: str
    refresh_token: str
    expires_at: float
    client_id: str
    client_secret: str
    organization_id: Optional[str]
    token_endpoint: str


class TokenStore:
    """Encrypted token store at ~/.upscaler/profiles/{profile}/."""

    SALT_FILE = ".salt"
    TOKEN_FILE = "tokens.enc"
    SALT_SIZE = 16

    def __init__(
        self,
        config_dir: Optional[str] = None,
        profile: Optional[str] = None,
    ):
        """Open the token store for `profile` (or the resolved active profile).

        Passing `config_dir` overrides profile resolution and points at an
        explicit directory; used by tests.
        """
        if config_dir is not None:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = get_profile_dir(profile)
        self._cached_key: Optional[bytes] = None

    def _get_key(self) -> bytes:
        """Get or derive the encryption key (cached within instance lifetime)."""
        if self._cached_key is None:
            salt = self._get_or_create_salt()
            self._cached_key = derive_key(salt)
        return self._cached_key

    def save(self, token_data: TokenData) -> None:
        """Encrypt and save token data with atomic write.

        Creates config dir (0o700), salt file (0o600) if needed,
        writes to .tmp then renames for atomicity.
        """
        ensure_profile_dir(self.config_dir)

        key = self._get_key()

        plaintext = json.dumps(asdict(token_data))
        ciphertext = encrypt(plaintext, key)

        token_path = self.config_dir / self.TOKEN_FILE
        tmp_path = self.config_dir / f"{self.TOKEN_FILE}.tmp"

        tmp_path.write_bytes(ciphertext)
        os.chmod(tmp_path, 0o600)
        tmp_path.rename(token_path)

    def load(self) -> TokenData:
        """Load and decrypt token data.

        Raises:
            RuntimeError: If not logged in or token store corrupted.
        """
        token_path = self.config_dir / self.TOKEN_FILE
        if not token_path.exists():
            raise RuntimeError("Not logged in. Run: upscaler login")

        salt_path = self.config_dir / self.SALT_FILE
        if not salt_path.exists():
            raise RuntimeError("Token store corrupted. Run: upscaler login")

        key = self._get_key()

        ciphertext = token_path.read_bytes()
        plaintext = decrypt(ciphertext, key)  # raises RuntimeError on failure

        data = json.loads(plaintext)
        return TokenData(**data)

    def delete(self) -> None:
        """Remove all token files."""
        for filename in (self.TOKEN_FILE, self.SALT_FILE, f"{self.TOKEN_FILE}.tmp"):
            path = self.config_dir / filename
            if path.exists():
                path.unlink()

    def is_expired(self) -> bool:
        """Check if access token has expired."""
        try:
            token_data = self.load()
            return time.time() >= token_data.expires_at
        except RuntimeError:
            return True

    def _get_or_create_salt(self) -> bytes:
        """Get existing salt or create a new one."""
        salt_path = self.config_dir / self.SALT_FILE
        if salt_path.exists():
            return salt_path.read_bytes()

        salt = os.urandom(self.SALT_SIZE)
        salt_path.write_bytes(salt)
        os.chmod(salt_path, 0o600)
        return salt
