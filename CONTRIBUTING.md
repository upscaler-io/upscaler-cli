# Contributing

Thanks for your interest in `upscaler-cli`. This guide covers the path from a
local checkout to a merged change.

## Before you start

- For a bug, open a [bug report](.github/ISSUE_TEMPLATE/bug_report.yml) with the
  failing command and `upscaler --version`.
- For a new command or flag, open a
  [feature request](.github/ISSUE_TEMPLATE/feature_request.yml) first. The CLI's
  surface is deliberately narrow and mirrors the Upscaler API, so it is worth
  agreeing on shape before you write code.
- Typos and doc fixes can go straight to a pull request.

## Local setup

```bash
git clone https://github.com/upscaler-io/upscaler-cli.git
cd upscaler-cli
python -m venv .venv && source .venv/bin/activate
make install          # pip install -e ".[dev]"
make test             # pytest
make lint             # flake8 + isort --check-only
make format           # black + isort
```

Point the CLI at a non-production server without editing any source:

```bash
upscaler --server https://your-upscaler-api.example.com health
# or persist it
upscaler config set server_url https://your-upscaler-api.example.com
```

## Layout

```
upscaler_cli/
├── __init__.py       # version + recommended agent-skills ref
├── config.py         # per-profile config, server URL resolution
├── profile.py        # profile resolution and on-disk layout
├── client.py         # httpx client, auth headers, 401 auto-refresh
├── errors.py         # error taxonomy surfaced to the user
├── uploads.py        # presign + S3 upload, Slate/form-field walkers
├── auth/             # OAuth 2.0 PKCE + DCR, Fernet token storage
├── formatters/       # table / tree / json renderers
└── cli/              # one module per command group, lazily loaded
```

## Conventions

- **Line length 100.** `black` and `isort` are configured in `pyproject.toml`;
  run `make format` before pushing.
- **Every command gets tests.** Mirror the existing structure under
  `tests/test_cli/`. HTTP is mocked with `respx`; never hit a real server.
- **Validate locally, fail fast.** Prefer rejecting bad input before the HTTP
  call, with a message naming the valid options.
- **Backend-mirrored constants stay in sync by hand.** A few values (upload
  persist fields, the MIME allowlist) mirror the closed-source backend. They are
  marked with a comment and locked by a test. If you change one, change the
  comment too.
- **Never print tokens.** See [SECURITY.md](SECURITY.md).

## Pull request checklist

- [ ] `make lint` passes.
- [ ] `make test` passes.
- [ ] New or changed behaviour has a test.
- [ ] `CHANGELOG.md` updated under **Unreleased**.
- [ ] `README.md` updated if you added or changed a command.

CI runs the same lint and test steps on Python 3.10 through 3.13, plus a build
check that fails if the wheel would ship anything other than a single
`upscaler_cli` top-level package.

## Releasing

Releases publish to [PyPI](https://pypi.org/project/upscaler-cli/) from
`.github/workflows/release.yml` via PyPI Trusted Publishing, so no API token is
stored in GitHub secrets.

1. Move the **Unreleased** section of `CHANGELOG.md` under the new version.
2. Bump `version` in `pyproject.toml` and `__version__` in
   `upscaler_cli/__init__.py` to match.
3. Land both on `main`.
4. Tag and push:

   ```bash
   git tag v0.4.0 && git push --tags
   ```

The workflow refuses to publish if the tag disagrees with `pyproject.toml`, so
bump first and tag second.

One-time PyPI setup, under the `upscaler-cli` project → Settings → Publishing:
owner `upscaler-io`, repository `upscaler-cli`, workflow `release.yml`,
environment `pypi`.

## Related projects

- [upscaler-skills](https://github.com/upscaler-io/upscaler-skills): agent
  skills that drive this CLI.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
