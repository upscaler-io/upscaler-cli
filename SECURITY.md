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
tokens to `~/.upscaler/profiles/<profile>/`, encrypted with Fernet. Anyone with
read access to that directory and the local key material can act as you, so
treat it like an SSH private key. `upscaler logout` removes the stored tokens
for the active profile.

The CLI never writes credentials to the repository, to logs, or to stdout.
`--verbose` prints only request metadata to stderr (method, URL, request id,
response status, response size) and never prints headers or bodies, so an
access token cannot leak through verbose output.
