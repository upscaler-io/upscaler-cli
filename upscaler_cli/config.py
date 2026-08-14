"""Persistent CLI configuration stored per profile.

Config lives at ~/.upscaler/profiles/{profile}/config.json. Resolution order:
    flag > env var > config file > profile default > _DEFAULT_SERVER_URL
"""

import json
import os
from pathlib import Path
from typing import Any, Optional

from upscaler_cli.profile import ensure_profile_dir, get_profile_dir, resolve_profile

# Default server for the `prod` profile and for any custom profile without an
# entry in _PROFILE_SERVER_DEFAULTS. Point somewhere else with either
# `upscaler config set server_url ...`, $UPSCALER_SERVER, or `--server`.
_DEFAULT_SERVER_URL = "https://ai.upscaler.app"

# Upscaler's own staging environment, reachable via `--profile dev`.
_STG_SERVER_URL = "https://ai.stg.upscaler.app"

_PROFILE_SERVER_DEFAULTS = {
    "prod": _DEFAULT_SERVER_URL,
    "dev": _STG_SERVER_URL,
}

DEFAULT_CONFIG = {
    "server_url": "",   # filled in per-profile on read
    "oauth_url": "",
    "default_format": "table",
    "verify_ssl": True,
}

VALID_KEYS = set(DEFAULT_CONFIG.keys())


def _profile_default_server_url(profile: str) -> str:
    return _PROFILE_SERVER_DEFAULTS.get(profile, _DEFAULT_SERVER_URL)


class CLIConfig:
    """Manages per-profile configuration in ~/.upscaler/profiles/{profile}/config.json."""

    CONFIG_FILE = "config.json"

    def __init__(
        self,
        config_dir: Optional[str] = None,
        profile: Optional[str] = None,
    ):
        """Open the config for `profile` (or the resolved active profile).

        Passing `config_dir` overrides profile resolution and points at an
        explicit directory; used by tests.
        """
        self.profile = profile or resolve_profile()
        if config_dir is not None:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = get_profile_dir(self.profile)
        self._config: Optional[dict] = None

    def _load(self) -> dict:
        """Load config from disk, or return defaults."""
        if self._config is not None:
            return self._config

        config_path = self.config_dir / self.CONFIG_FILE
        if config_path.exists():
            try:
                self._config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._config = dict(DEFAULT_CONFIG)
        else:
            self._config = dict(DEFAULT_CONFIG)
        return self._config

    def get(self, key: str) -> Any:
        """Get a config value, falling back to profile-aware defaults."""
        config = self._load()
        if key in config and config[key] not in (None, ""):
            return config[key]
        if key == "server_url":
            return _profile_default_server_url(self.profile)
        return DEFAULT_CONFIG.get(key)

    def set(self, key: str, value: Any) -> None:
        """Set a config value and persist to disk."""
        if key not in VALID_KEYS:
            raise ValueError(
                f"Unknown config key: {key}. "
                f"Valid keys: {', '.join(sorted(VALID_KEYS))}"
            )

        config = self._load()
        config[key] = value
        self._save(config)

    def _save(self, config: dict) -> None:
        """Write config to disk."""
        ensure_profile_dir(self.config_dir)
        config_path = self.config_dir / self.CONFIG_FILE
        config_path.write_text(json.dumps(config, indent=2))
        self._config = config

    def resolve_server_url(
        self, flag_value: Optional[str] = None
    ) -> str:
        """Resolve server URL: flag > env > profile config > profile default.

        Args:
            flag_value: --server flag value (highest priority).

        Returns:
            Resolved server URL string.
        """
        if flag_value:
            return flag_value
        env_value = os.environ.get("UPSCALER_SERVER")
        if env_value:
            return env_value
        return self.get("server_url") or ""

    def resolve_verify_ssl(self) -> bool:
        """Resolve SSL verification: env > config > default (True).

        Set to False for self-signed certs in dev/staging:
            upscaler config set verify_ssl false
            UPSCALER_VERIFY_SSL=false upscaler health
        """
        env_value = os.environ.get("UPSCALER_VERIFY_SSL")
        if env_value is not None:
            return env_value.lower() not in ("false", "0", "no")
        val = self.get("verify_ssl")
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() not in ("false", "0", "no")
        return True
