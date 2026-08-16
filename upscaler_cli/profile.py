"""Profile resolution and on-disk layout.

A profile is an isolated bucket of CLI state (config.json, tokens, salt, pending
device code) so users can keep separate auth keys for different environments
(e.g. prod vs dev) and switch via --profile.

Resolution priority:   flag > $UPSCALER_PROFILE > saved default > "prod"

The saved default is written by `upscaler profile set-default <name>` to
~/.upscaler/default_profile (plain text, just the profile name).

On-disk layout:
    ~/.upscaler/
    +- default_profile
    +- profiles/
       +- prod/
       |  +- config.json
       |  +- tokens.enc
       |  +- .salt
       |  +- pending_device.json
       +- dev/
          +- ...

Legacy layout (config + tokens directly under ~/.upscaler/) is auto-migrated to
the prod profile on first access.
"""

import os
import re
from pathlib import Path
from typing import Optional

DEFAULT_PROFILE = "prod"
PROFILE_ENV_VAR = "UPSCALER_PROFILE"
DEFAULT_PROFILE_FILE = "default_profile"

_LEGACY_FILES = ("config.json", "tokens.enc", ".salt", "pending_device.json")

# Profile names must be filesystem-safe, no path separators, no leading dot.
_VALID_PROFILE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def resolve_profile(flag_value: Optional[str] = None) -> str:
    """Pick the active profile name from flag, env, saved default, or "prod"."""
    if flag_value:
        return validate_profile(flag_value)
    env_value = os.environ.get(PROFILE_ENV_VAR)
    if env_value:
        return validate_profile(env_value)
    saved = get_saved_default()
    if saved:
        return saved
    return DEFAULT_PROFILE


def get_saved_default() -> Optional[str]:
    """Return the profile saved by `upscaler profile set-default`, or None.

    Unreadable, empty, or invalid file content all mean "no saved default".
    """
    path = upscaler_home() / DEFAULT_PROFILE_FILE
    try:
        name = path.read_text().strip()
    except OSError:
        return None
    if not name:
        return None
    try:
        return validate_profile(name)
    except ValueError:
        return None


def save_default_profile(name: str) -> Path:
    """Persist `name` as the saved default profile; return the file path."""
    from upscaler_cli.security import ensure_private_dir, write_private_text

    validate_profile(name)
    home = upscaler_home()
    ensure_private_dir(home)
    path = home / DEFAULT_PROFILE_FILE
    write_private_text(path, name + "\n")
    return path


def validate_profile(name: str) -> str:
    """Reject names that would escape the profile dir or shadow dotfiles."""
    if not _VALID_PROFILE_RE.match(name or ""):
        raise ValueError(
            f"Invalid profile name: {name!r}. "
            "Use letters, digits, '.', '_', '-' (1-64 chars, no leading dot)."
        )
    return name


def upscaler_home() -> Path:
    """Root of CLI state. Honors $UPSCALER_HOME for tests."""
    return Path(os.environ.get("UPSCALER_HOME") or os.path.expanduser("~/.upscaler"))


def profiles_root() -> Path:
    return upscaler_home() / "profiles"


def get_profile_dir(profile: Optional[str] = None) -> Path:
    """Return the dir for `profile`, after migrating any legacy root state.

    When `profile` is None, resolves from $UPSCALER_PROFILE / the default,
    so callers can pass through an unset value without an extra fallback.
    """
    migrate_legacy_root()
    return profiles_root() / resolve_profile(profile)


def list_profiles() -> list[str]:
    """Return sorted list of profile names that have a dir on disk."""
    root = profiles_root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def ensure_profile_dir(config_dir: Path) -> None:
    """Create `config_dir` and any parent up to ~/.upscaler/ with 0o700.

    Workaround for Path.mkdir(parents=True), which honors umask (typically
    0o755) on intermediate dirs. Token + config files are 0o600, but the
    enclosing profiles/ dir leaking the list of profile names is still a
    confidentiality regression vs. the pre-profile single-dir layout.

    The mode is re-asserted on every call, not just at creation: mkdir(mode=...,
    exist_ok=True) silently leaves an existing directory as it found it, so a
    tree left group- or world-readable by an older version, a backup restore, or
    a stray chmod would otherwise keep that mode indefinitely — and the 0600
    files inside are only unreachable to other local users because of these bits.
    """
    from upscaler_cli.security import ensure_private_dir

    ensure_private_dir(upscaler_home())
    ensure_private_dir(profiles_root())
    ensure_private_dir(config_dir)


def migrate_legacy_root() -> bool:
    """Move pre-profile state at ~/.upscaler/ into profiles/prod/.

    Idempotent. Runs once: if profiles/ already exists OR no legacy files are
    present, this is a no-op. Returns True if a migration happened.
    """
    home = upscaler_home()
    if not home.exists():
        return False
    if profiles_root().exists():
        return False

    legacy_present = [name for name in _LEGACY_FILES if (home / name).exists()]
    if not legacy_present:
        return False

    dest = home / "profiles" / DEFAULT_PROFILE
    ensure_profile_dir(dest)

    for name in legacy_present:
        src = home / name
        dst = dest / name
        # Preserve mode by using rename (same filesystem under HOME).
        src.rename(dst)

    return True
