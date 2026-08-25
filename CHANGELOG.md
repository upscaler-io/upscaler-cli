# Changelog

All notable changes to `upscaler-cli` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
