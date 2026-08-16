"""Shared security primitives: origin binding, path safety, and secure file writes.

Three concerns live here because they are enforced from several modules and must
agree on one definition:

- ``same_origin`` / ``origin_of`` back the token-origin binding in
  ``UpscalerClient``: a bearer token is only ever presented to the server that
  issued it.
- ``validate_request_path`` rejects request paths that carry traversal or a
  query/fragment, so an asset id interpolated into an f-string path cannot
  re-target the request.
- ``write_private_bytes`` / ``write_private_text`` create files that are 0600
  from the first byte, rather than writing under the ambient umask and
  narrowing the mode afterwards.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

# Scheme -> default port, used so https://h and https://h:443 compare equal.
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Characters that would let an id escape its path segment and re-target the
# request: separators, a query/fragment start, an encoded-escape lead-in, and
# anything the URL parser may normalize.
_UNSAFE_PATH_CHARS = frozenset('/\\?#%"\'<>{}|^`')


def origin_of(url: str) -> Optional[tuple]:
    """Return ``(scheme, host, port)`` for `url`, or None if it has no origin.

    Host is lower-cased and the scheme's default port is filled in, so
    ``https://api.example.com`` and ``https://API.example.com:443`` share an
    origin.

    Returns None unless the URL carries an explicit http/https scheme and a
    host. A scheme-less or malformed value has no origin to compare, and
    inferring one would let a string like ``"not a url"`` parse as a host and
    match itself — so callers get None and fail closed instead.
    """
    if not url:
        return None
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in _DEFAULT_PORTS:
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    try:
        port = parts.port
    except ValueError:
        # Malformed port (e.g. "https://h:notaport") — treat as no origin so
        # the caller fails closed rather than comparing garbage.
        return None
    return scheme, host, port or _DEFAULT_PORTS[scheme]


def same_origin(a: str, b: str) -> bool:
    """True when both URLs resolve to the same (scheme, host, port).

    Returns False when either side has no determinable origin, so an unusable
    value never counts as a match.
    """
    origin_a = origin_of(a)
    origin_b = origin_of(b)
    if origin_a is None or origin_b is None:
        return False
    return origin_a == origin_b


def validate_request_path(path: str) -> str:
    """Return `path` unchanged, or raise if it could re-target the request.

    Commands build request paths with f-strings around caller-supplied ids
    (``f"/api/v1/assets/{asset_id}"``). httpx resolves ``..`` segments and
    splits on ``?``/``#`` when it parses the URL, so an id like
    ``d_x/../../admin`` silently sends the request — and the bearer token —
    to a different endpoint than the command intended. Reject those here, at
    the single point every command funnels through.

    Raises:
        CLIError: If the path is relative, carries a query/fragment, or
            contains a traversal or empty segment.
    """
    from upscaler_cli.errors import CLIError

    if not path.startswith("/"):
        raise CLIError(f"Invalid request path (must be absolute): {path!r}")

    if "?" in path or "#" in path:
        raise CLIError(
            "Invalid id in request path: a query string or fragment is not "
            "allowed in a path segment. Pass query parameters via params=."
        )

    for segment in path.split("/")[1:]:
        if segment in ("", ".", ".."):
            raise CLIError(
                f"Invalid id in request path: {path!r} contains an empty or "
                "relative path segment."
            )
        if any(ch in segment for ch in "\r\n\t") or any(ord(ch) < 0x20 for ch in segment):
            raise CLIError("Invalid id in request path: control characters are not allowed.")

    return path


def validate_id(value: str, *, label: str = "id") -> str:
    """Return `value` if it is safe to interpolate into a URL path segment.

    Ids are opaque server-issued strings, so this rejects only the characters
    that carry structural meaning in a URL rather than imposing a format.

    Raises:
        CLIError: If the value is empty or contains a path/query separator.
    """
    from upscaler_cli.errors import CLIError

    if not value:
        raise CLIError(f"Invalid {label}: value is empty.")
    bad = sorted({ch for ch in value if ch in _UNSAFE_PATH_CHARS})
    if bad:
        raise CLIError(
            f"Invalid {label}: {value!r} contains disallowed character(s) "
            f"{''.join(bad)!r}."
        )
    if any(ord(ch) < 0x20 or ch.isspace() for ch in value):
        raise CLIError(f"Invalid {label}: {value!r} contains whitespace or control characters.")
    return value


def write_private_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` with mode 0600, never wider — not even briefly.

    ``Path.write_bytes`` followed by ``os.chmod`` leaves the file readable per
    the ambient umask (typically 0644) for the window between the two calls.
    Opening with an explicit mode and O_CREAT closes that window; the file is
    0600 before any byte is written. An existing file is truncated and its
    mode re-asserted, so a file left wide by an earlier version is repaired.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        # Refuse to write through a symlink planted at the destination.
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, data)
    finally:
        os.close(fd)


def write_private_text(path: Path, text: str) -> None:
    """UTF-8 counterpart of write_private_bytes."""
    write_private_bytes(path, text.encode("utf-8"))


def ensure_private_dir(path: Path) -> None:
    """Create `path` as 0700 and re-assert that mode if it already exists.

    ``mkdir(mode=0o700, exist_ok=True)`` is a no-op on an existing directory,
    so a profile directory left group/world-readable by an earlier version, a
    restore, or a careless chmod keeps that mode forever — and every 0600 file
    inside it only stays unreachable because of the directory bits.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        current = path.stat().st_mode & 0o777
    except OSError:
        return
    if current != 0o700:
        try:
            path.chmod(0o700)
        except OSError:
            # Not fatal: a directory we cannot chmod (e.g. an odd mount) should
            # not break the command, and the files inside are still 0600.
            pass
