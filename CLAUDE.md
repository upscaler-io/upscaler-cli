# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make install                        # pip install -e ".[dev]"; refuses to run outside a venv
make test                           # pytest tests/ -v
make lint                           # flake8 + isort --check-only (line length 100)
make format                         # black + isort (run before pushing)

python -m pytest tests/test_cli/test_entry.py -v                    # one file
python -m pytest tests/test_cli/test_entry.py::TestEntryCreate -v   # one class
python -m pytest tests/ -k "upload and not table" -v                # by expression
```

`make install` guards on `sys.prefix != sys.base_prefix` and exits 1 outside a virtualenv,
because a pyenv shim makes an unactivated `pip` resolve to the ambient interpreter instead
of failing. `SKIP_VENV_CHECK=1` bypasses it for CI runners and containers.

Unit tests never hit the network: HTTP is mocked with `respx`, and `tests/conftest.py`
has an autouse fixture that strips `UPSCALER_*` env vars and pins `$UPSCALER_HOME` to a
tmp dir, so a developer shell with `UPSCALER_OUTPUT=json` set cannot break assertions.

Live integration tests are double-gated and skip by default:

```bash
upscaler --profile dev login        # one-time; dev resolves to staging
UPSCALER_INTEGRATION_TEST=1 python -m pytest tests/test_integration -v
```

`tests/test_integration/conftest.py` refuses to run against any host outside
`_NONPROD_HOSTS` (staging plus localhost), so a misconfigured profile cannot fire
destructive tests at production.

CI (`.github/workflows/test.yml`) runs lint + tests on Python 3.10 to 3.13, plus a build
job that inspects the wheel and fails if the top-level packages are anything other than
exactly `{"upscaler_cli"}`.

## Architecture

A thin Click front end over the Upscaler REST API. Every command follows the same path:

```
cli/<group>.py  ->  helpers.make_client(ctx)  ->  UpscalerClient.request()  ->  REST
                                    |                        |
                        CLIConfig + TokenStore      auth header, X-Request-Id,
                        (per-profile, on disk)      auto-refresh + retry on 401
```

`client.py` is the only module that talks HTTP to the API (`uploads.py` is the exception:
it POSTs file bodies straight to S3 with a presigned form). It raises `APIError` on
HTTP >= 400 and `AuthRequiredError` when there is no usable token.

**Profiles are the root of all local state.** `profile.py` resolves the active profile
(flag > `$UPSCALER_PROFILE` > saved default > `prod`) and owns the on-disk layout under
`~/.upscaler/profiles/<name>/` (config.json, tokens.enc, .salt). It also auto-migrates the
pre-0.x flat layout on first access. `CLIConfig` and `TokenStore` both take an optional
`profile`, and both accept a `config_dir` override that exists purely for tests. Directory
creation goes through `ensure_profile_dir` rather than `mkdir(parents=True)` so umask
cannot widen the 0o700 mode on intermediate dirs.

**Tokens are machine-bound.** `auth/encryption.py` derives the Fernet key from
`hostname:username` plus a random salt via PBKDF2 (480k iterations), so a `tokens.enc`
copied to another machine fails to decrypt with an actionable message rather than a stack
trace. `auth/oauth.py` runs OAuth 2.0 Authorization Code + PKCE with Dynamic Client
Registration and a localhost callback server, and also implements the device-code fallback.

### Two failure channels, not one

The API can fail in two different ways, and both must be handled:

1. HTTP >= 400, which `client.request` turns into `APIError`.
2. HTTP 200 with `{"success": false, "error": {...}, "data": []}`. This is what the
   platform's native tools emit for things like a missing organization context.

Channel 2 is the trap: a read command that only looks at `data` renders it as "No results"
and exits 0. Guard reads with `helpers.raise_on_envelope_error(ctx, result)` and emit
writes through `helpers.emit_action_result`, which checks the same flag. Every new command
that touches the API needs one of the two.

Exit codes are defined in `errors.py`: 0 success, 1 error, 2 authentication required.
Route exceptions through `helpers.handle_error(ctx, e)` so the code and the output mode
stay consistent.

### Output contract

Three mutually aware modes, all resolved in `helpers`, not in individual commands:

- `--json`: compact envelope on stdout. Default flips to on when `$UPSCALER_OUTPUT=json`.
- `--quiet`: only the resolved id. If a success envelope carries no id, `emit_action_result`
  exits non-zero rather than printing an empty line, because callers capture that id.
- human: `"<label>: <id>"`, or a table/tree from `formatters/`.

Write commands additionally take `--dry-run`, rendered by `helpers.emit_dry_run`. Agents are
the primary consumer of all four, so treat their shape as a public interface.

### Global flags are position-independent

`main.py` defines `--json`, `--quiet`, `--verbose`, `--server`, and `--profile` on the root
group, which Click would normally only accept before the subcommand. `GlobalFlagGroup`
overrides `parse_args` to hoist them to the front first, so `upscaler list entries --json`
works as well as `upscaler --json list entries`. The hoister walks the whole subcommand tree
to learn which options take a value, so a token sitting in a value position
(`--title "--quiet"`) is left alone, and it stops at `--`. Adding a new global flag means
updating `_GLOBAL_BOOL_FLAGS` or `_GLOBAL_VALUE_OPTS`.

### Command groups

One module per group under `cli/`, registered at the bottom of `main.py`. Imports of
`helpers`, `formatters`, `asyncio`, and `httpx` sit *inside* command function bodies rather
than at module top, which keeps `upscaler --help` startup fast; follow that pattern.

Two shapes exist:

- **Action-dispatch groups** (`todo`, `automation`, `framework`) serialize the command as
  `{"action": "...", ...}` to a single endpoint and share `helpers.execute_rest_action`,
  which handles dry-run, the client call, error routing, and rendering in one place.
- **Direct-endpoint commands** (`get`, `list`, `entry`, `asset`, `files`, `comment`,
  `recover`) build their own request. `get.py` shows the routing convention: resource ids
  are prefix-routed (`g_` group, `t_` task, and `d_`/`rg_`/`rd_`/`r_`/`i_`/`cd_`/`to_` to
  `/api/v1/assets`), with `--type` as the explicit escape hatch for ids that have no
  prefix, such as member uids. No prefix may be a prefix of another; if that ever changes,
  order the longer one first.

Definition assets exist in two lanes under one id: the `designer` working copy and the
`published` snapshot. Reads default to published. `--lane designer` is what you want when
the result feeds an edit back, since content writes target the designer copy.

### File uploads

`uploads.py` presigns via `/api/v1/files/presign`, POSTs the body to S3, then splices the
returned file-item into the entry's values. Two value shapes are supported: Pattern A, a
Slate tree (documents), and Pattern B, a flat `ff_*` dict (items and records). Splices are
idempotent on `uid`.

`entry.py` orchestrates the risky part and the ordering is deliberate: fetch the agent
schema, resolve `--field <label>` to `ff_*`, and hard-fail on unknown, ambiguous, or
non-file fields **before** anything is uploaded to S3. Then read current values plus
version, upload, splice, and send one mutation. On `ITEM_VERSION_CONFLICT` (items only) it
re-reads and retries within `_CONFLICT_RETRY_BUDGET`; task drafts are last-writer-wins. A
mid-batch upload failure best-effort deletes the uids that already landed.

Nested table columns have a schema/persistence mismatch worth knowing about: the schema
endpoint reports a column key as `ff_table.ff_col`, but the persisted row and every UI
renderer key it by the bare `ff_col`. `_bare_col_key` reduces to the bare form. Accept
either spelling until the backend fix ships.

### Cross-repo constants

A few values mirror the closed-source backend and are locked by tests, because drift here
fails silently (the server accepts the request and drops the data):

- `uploads.FILE_ITEM_PERSIST_FIELDS` mirrors `normalizeFileBlocks.js`.
- `uploads._EXTENSION_OVERRIDES` values must all exist in the backend's
  `INTERNAL_FILE_UPLOAD_ALLOWED_TYPES` allowlist; `tests/test_uploads.py` locks the pairing.
- `entry.AGENT_SCHEMA_FILE_UPLOAD_TYPE` must equal the string the backend's `form-upload.js`
  emits; `tests/test_cli/test_agent_schema_contract.py` is that boundary check, and it
  exists because the CLI once filtered on `"form-upload"` while the backend emitted
  `"file_upload"` and neither side's tests crossed the line.
- `helpers.validate_entry_data` rejects top-level `ff_*` keys for the same reason: the
  `/entries` endpoint reads form values only from `data.values`, and a bare payload returns
  a successful-looking response with the values dropped.
- `get._ASSET_PREFIXES` mirrors `_detect_asset_type`'s `prefix_map` in up-ai's
  `tools/native/_helpers.py`. A prefix the server knows but the CLI does not is rejected
  locally with unhelpful advice, so the id becomes unreadable until a CLI release ships.
- `get._FORMATS` mirrors the format names `get_asset` branches on in up-ai's
  `document_tools.py`. The server does not reject an unknown format; it returns an empty
  data object, so this list is the only thing that turns a typo into an error.

When you change one of these, change the comment naming the backend file too.

## Conventions

- Validate locally and fail fast, with a message that names the valid options. Several
  helpers exist only to turn a silent server-side no-op into a loud client-side usage error.
- Write commands accept `--data` as inline JSON, `@file.json`, or `-` for stdin, via
  `helpers.parse_data`.
- Publishing and approval are deliberately not exposed as commands. Those stay human-gated
  in the web app, and agent writes land as drafts carrying a reviewer `--note`.
- Never print tokens. `--verbose` prints request metadata only (method, URL, request id,
  status, byte count), never headers or bodies.
- The installed package is `upscaler_cli`. It was renamed from a top-level `src` in 0.4.0
  to stop squatting a common module name, and the CI wheel check exists to keep it that way.

## Releasing

Bump `version` in `pyproject.toml` and `__version__` in `upscaler_cli/__init__.py` together,
move the `CHANGELOG.md` Unreleased section under the new version, land on `main`, then tag.
`RECOMMENDED_SKILLS_REF` in `__init__.py` pins the matching
[upscaler-skills](https://github.com/upscaler-io/upscaler-skills) release and is printed by
`upscaler --version`; bump it alongside. The release workflow refuses to publish if the tag
disagrees with `pyproject.toml`, so bump first and tag second. Full process in
[CONTRIBUTING.md](CONTRIBUTING.md).
