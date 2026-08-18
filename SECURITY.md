# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Email **support@upscaler.io** with a description, reproduction steps, and the
CLI version (`upscaler --version`). We aim to acknowledge within 3 business
days and to ship a fix or a mitigation plan within 30 days.

## Scope

This repository is the `upscaler-cli` client. Vulnerabilities in the Upscaler
API or web application are in scope for the same address but are tracked
separately.

## What the CLI stores locally

`upscaler login` completes an OAuth 2.0 PKCE flow and writes the resulting
tokens to `~/.upscaler/profiles/<profile>/`. The directory is `0700` and every
file in it is `0600`. `upscaler logout` revokes both the access and the refresh
token server-side, then removes the stored tokens and any unredeemed device
code for the active profile.

### What the at-rest encryption does and does not protect

Tokens are encrypted with Fernet under a key derived (PBKDF2-HMAC-SHA256,
480,000 iterations) from `hostname:username` plus a random salt stored beside
the ciphertext.

Be clear about what that buys you. The key inputs are **not secret**: the salt
sits in the same directory as the token file, and the hostname and username are
readable by any local process. Anyone who can read the profile directory can
re-derive the key and recover your tokens. The encryption defeats casual
disclosure — a token file swept into a backup, a synced folder, a support
bundle, or a stray `cat` — and it makes a token file useless on a *different*
machine. It is **not** a defence against a local attacker or malware running as
your user.

So the file permissions, not the encryption, are what keep another user on the
same host out. Treat `~/.upscaler/` like an SSH private key: on a shared or
multi-user machine, assume anyone who can read that directory can act as you.
Use `upscaler logout` when you are done on a host you do not control.

### Credentials only go to the server that issued them

The CLI refuses to send a stored token to any origin other than the one that
issued it, so a crafted `--server`, a `$UPSCALER_SERVER` inherited from a
poisoned environment, or an altered `config.json` cannot redirect your access
token to a third party. Pointing the CLI at a different server means logging in
there — ideally under its own profile:

```bash
upscaler --profile staging login
```

The CLI also warns on stderr when a request would travel over plaintext HTTP or
with TLS verification disabled (`verify_ssl false`). Both are supported for
local development, and both mean the access token is exposed to anyone on the
network path — do not use them against a server holding real data.

### Logging

The CLI never writes credentials to the repository, to logs, or to stdout.
`--verbose` prints only request metadata to stderr (method, URL, request id,
response status, response size) and never prints headers or bodies, so an
access token cannot leak through verbose output.

### Destructive commands in non-interactive use

`upscaler <asset|entry|todo|comment|automation> delete` prompts for
confirmation only on an interactive terminal. Under `--json`, in a pipeline, in
CI, or when driven by an agent, the prompt is skipped by design so automation
does not hang. Use `--dry-run` to preview any write, and gate destructive
commands in scripts and agent workflows yourself.
