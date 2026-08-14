"""Tests for upscaler_cli.profile: resolution, paths, and legacy migration."""

import pytest

from upscaler_cli.profile import (
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_FILE,
    get_profile_dir,
    get_saved_default,
    list_profiles,
    migrate_legacy_root,
    profiles_root,
    resolve_profile,
    save_default_profile,
    upscaler_home,
    validate_profile,
)

# ---- resolve_profile ----


def test_default_is_prod(monkeypatch):
    monkeypatch.delenv("UPSCALER_PROFILE", raising=False)
    assert resolve_profile() == "prod"
    assert DEFAULT_PROFILE == "prod"


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("UPSCALER_PROFILE", "dev")
    assert resolve_profile() == "dev"


def test_flag_overrides_env(monkeypatch):
    monkeypatch.setenv("UPSCALER_PROFILE", "dev")
    assert resolve_profile("staging") == "staging"


def test_invalid_profile_rejected():
    for bad in ("../escape", "with/slash", ".dotleader", "", " "):
        with pytest.raises(ValueError):
            validate_profile(bad)


def test_valid_profile_names_accepted():
    for ok in ("prod", "dev", "staging-2", "team_a", "v1.2"):
        assert validate_profile(ok) == ok


# ---- saved default (profile set-default) ----


def test_saved_default_used_when_no_flag_or_env(monkeypatch):
    monkeypatch.delenv("UPSCALER_PROFILE", raising=False)
    save_default_profile("dev")
    assert resolve_profile() == "dev"


def test_env_beats_saved_default(monkeypatch):
    save_default_profile("dev")
    monkeypatch.setenv("UPSCALER_PROFILE", "staging")
    assert resolve_profile() == "staging"


def test_flag_beats_env_and_saved_default(monkeypatch):
    save_default_profile("dev")
    monkeypatch.setenv("UPSCALER_PROFILE", "staging")
    assert resolve_profile("team_a") == "team_a"


def test_saved_default_missing_file_returns_none():
    assert get_saved_default() is None


def test_saved_default_empty_file_returns_none():
    home = upscaler_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / DEFAULT_PROFILE_FILE).write_text("  \n")
    assert get_saved_default() is None
    assert resolve_profile() == DEFAULT_PROFILE


def test_saved_default_invalid_content_ignored():
    home = upscaler_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / DEFAULT_PROFILE_FILE).write_text("../escape\n")
    assert get_saved_default() is None
    assert resolve_profile() == DEFAULT_PROFILE


def test_save_default_profile_writes_file():
    path = save_default_profile("dev")
    assert path == upscaler_home() / DEFAULT_PROFILE_FILE
    assert path.read_text() == "dev\n"
    assert (path.stat().st_mode & 0o777) == 0o600


def test_save_default_profile_rejects_invalid_name():
    with pytest.raises(ValueError):
        save_default_profile("with/slash")
    assert not (upscaler_home() / DEFAULT_PROFILE_FILE).exists()


# ---- get_profile_dir ----


def test_profile_dir_layout(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    expected = tmp_path / "home" / "profiles" / "prod"
    assert get_profile_dir() == expected


def test_named_profile_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    assert get_profile_dir("dev") == tmp_path / "home" / "profiles" / "dev"


# ---- legacy migration ----


def test_migration_moves_legacy_files(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("UPSCALER_HOME", str(home))

    (home / "config.json").write_text('{"server_url": "https://legacy.example"}')
    (home / "tokens.enc").write_bytes(b"ciphertext")
    (home / ".salt").write_bytes(b"saltsaltsaltsalt")

    moved = migrate_legacy_root()

    assert moved is True
    prod = home / "profiles" / "prod"
    assert (prod / "config.json").read_text().startswith("{")
    assert (prod / "tokens.enc").read_bytes() == b"ciphertext"
    assert (prod / ".salt").read_bytes() == b"saltsaltsaltsalt"
    # Legacy locations gone
    assert not (home / "config.json").exists()
    assert not (home / "tokens.enc").exists()
    assert not (home / ".salt").exists()


def test_migration_is_idempotent(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("UPSCALER_HOME", str(home))

    (home / "config.json").write_text("{}")
    migrate_legacy_root()
    # second call: profiles/ exists, so noop
    assert migrate_legacy_root() is False


def test_migration_skipped_when_profiles_dir_exists(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "profiles" / "prod").mkdir(parents=True)
    monkeypatch.setenv("UPSCALER_HOME", str(home))

    # Stray legacy config alongside profiles/: leave it alone, don't clobber.
    (home / "config.json").write_text("{}")
    assert migrate_legacy_root() is False
    assert (home / "config.json").exists()


def test_migration_skipped_when_no_legacy_files(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("UPSCALER_HOME", str(home))
    assert migrate_legacy_root() is False


# ---- list_profiles ----


def test_list_profiles_returns_subdirs(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("UPSCALER_HOME", str(home))
    for name in ("prod", "dev", "staging"):
        (home / "profiles" / name).mkdir(parents=True)
    # Stray file shouldn't appear
    (home / "profiles" / "README.txt").write_text("x")
    assert list_profiles() == ["dev", "prod", "staging"]


def test_list_profiles_empty_when_no_profiles_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "home"))
    assert list_profiles() == []


# ---- upscaler_home honors env var ----


def test_upscaler_home_env(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSCALER_HOME", str(tmp_path / "custom"))
    assert upscaler_home() == tmp_path / "custom"
    assert profiles_root() == tmp_path / "custom" / "profiles"


def test_upscaler_home_falls_back_to_homedir(monkeypatch, tmp_path):
    monkeypatch.delenv("UPSCALER_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    assert upscaler_home() == tmp_path / "userhome" / ".upscaler"
