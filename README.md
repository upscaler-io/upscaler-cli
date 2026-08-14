# Upscaler CLI

[![PyPI](https://img.shields.io/pypi/v/upscaler-cli)](https://pypi.org/project/upscaler-cli/)
[![Python](https://img.shields.io/pypi/pyversions/upscaler-cli)](https://pypi.org/project/upscaler-cli/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![test](https://github.com/upscaler-io/upscaler-cli/actions/workflows/test.yml/badge.svg)](https://github.com/upscaler-io/upscaler-cli/actions/workflows/test.yml)

Command-line tool for searching, retrieving, and managing Upscaler documents, records, and workflows.

Built for humans at a terminal and for AI agents alike: every command takes
`--json` for machine-readable output, and write commands take `--dry-run`.
The companion [agent skills](https://github.com/upscaler-io/upscaler-skills)
drive this CLI from Claude Code, Cursor, Gemini CLI, and Codex.

## Install

```bash
pip install upscaler-cli
```

## Setup

```bash
upscaler login
```

That is the whole setup. The CLI talks to `https://ai.upscaler.app` by
default. Point it elsewhere only if you need to:

```bash
upscaler config set server_url https://your-upscaler-api.example.com
```

For a self-hosted or staging server with self-signed certificates:

```bash
upscaler config set verify_ssl false
```

## Quick Start

```bash
# Check connection
upscaler health

# Search documents
upscaler search "safety procedures"

# Get an asset
upscaler get rg_abc123
upscaler get rg_abc123 --format schema
upscaler get rg_abc123 --format markdown

# List data
upscaler list definitions
upscaler list entries --definition-id rg_abc123
upscaler list todos

# View hierarchy
upscaler hierarchy d_abc123

# Manage todos
upscaler todo create --title "Review document"
upscaler todo close to_abc123

# Manage entries
upscaler entry create --definition-id rg_abc123 --data '{"title": "New item"}'
upscaler entry create --definition-id rg_abc123 --data @payload.json

# Get members and groups
upscaler get <firebase_uid> --type member
upscaler get g_abc123

# Discover members and groups (OWNER/ADMIN) for assignment / @mentions
upscaler list members --search kong
upscaler list groups

# Comments on todos and releases
upscaler comment list --asset-id to_abc123 --asset-type todo
upscaler comment add --asset-id to_abc123 --asset-type todo \
  --content "Reviewed and approved" --mention member::<uid>

# Download an evidence file (AV-gated); or just get the signed URL
upscaler files download --key <key> --name report.pdf --output ./report.pdf
upscaler files sign-get --key <key> --name report.pdf

# Recover a soft-deleted asset (and find recovery targets)
upscaler list deleted --search policy
upscaler recover d_abc123 --dry-run
upscaler recover d_abc123
```

## Global Flags

Global flags go **before** the command:

```bash
upscaler --json list todos          # JSON output
upscaler --verbose search "audit"   # show HTTP details
upscaler --server https://... health  # override server URL
upscaler --version                  # print version
```

## Write Safety

Preview changes before committing:

```bash
upscaler entry create --definition-id rg_123 --data @payload.json --dry-run
upscaler asset delete --asset-id rg_123 --dry-run
```

## Data Input

Write commands accept `--data` in three forms:

```bash
--data '{"key": "value"}'          # inline JSON
--data @payload.json               # from file (recommended)
--data -                           # from stdin
```

## Configuration

```bash
upscaler config set server_url https://api.example.com
upscaler config set verify_ssl false
upscaler config get server_url
```

Settings are stored per profile at `~/.upscaler/profiles/<profile>/config.json`.
Resolution order is **flag > environment variable > config file > profile
default**, so `--server` beats `$UPSCALER_SERVER`, which beats the stored
config. The relevant environment variables are `UPSCALER_SERVER`,
`UPSCALER_VERIFY_SSL`, `UPSCALER_PROFILE`, and `UPSCALER_OUTPUT`.

## Profiles

Each profile carries its own credentials and config, so you can hold a session
against more than one environment at a time. `prod` is the default.

```bash
upscaler --profile dev login     # dev defaults to Upscaler's staging server
upscaler --profile dev list todos
upscaler profile list
upscaler profile set-default dev
```

## Auth Commands

```bash
upscaler login       # browser-based OAuth2 login
upscaler status      # check auth state + token expiry
upscaler refresh     # refresh expired token
upscaler logout      # revoke and clear tokens
```

## All Commands

Run `upscaler --help` for the full command list, or `upscaler <command> --help` for details on any command.

## Using this CLI from an AI agent

[upscaler-skills](https://github.com/upscaler-io/upscaler-skills) packages
Upscaler workflows as portable agent skills that shell out to this CLI. They
cover compliance Q&A, authoring asset definitions, writing register entries,
and completing records, and install into Claude Code, Cursor, Gemini CLI, and
Codex.

Publishing and approval are deliberately **not** exposed to agents. Those stay
human-gated in the web app.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, conventions, and the
release process. Bug reports and feature requests go through the
[issue templates](https://github.com/upscaler-io/upscaler-cli/issues/new/choose).

## Security

Report vulnerabilities privately to **support@upscaler.io**, not via a public
issue. See [SECURITY.md](SECURITY.md) for what the CLI stores locally.

## License

[MIT](LICENSE)
