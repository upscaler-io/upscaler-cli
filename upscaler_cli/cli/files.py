"""Low-level file presign CLI command.

Exposes ``upscaler files presign --file-name X --content-type Y`` as an
escape hatch for scripts that drive the S3 upload themselves. The default
file-upload path goes through ``upscaler entry update --file FIELD=PATH``,
which composes presign + multipart upload + values mutation.
"""

import asyncio
import os
import sys
from pathlib import Path

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.cli.helpers import handle_error, make_client
from upscaler_cli.errors import CLIError
from upscaler_cli.formatters.json_fmt import format_json

# Streamed download chunk size. Matches the "8 KiB chunks" contract so a large
# evidence file never buffers wholly in memory.
_DOWNLOAD_CHUNK = 8192


@click.group("files")
def files_group():
    """File upload/download primitives.

    Examples:
        upscaler files presign --file-name report.pdf --content-type application/pdf
        upscaler files download --key <key> --name report.pdf --output ./report.pdf
        upscaler files sign-get --key <key> --name report.pdf
    """
    pass


def _resolve_download_url(ctx, key, name, bucket):
    """Call the sign-get REST route and return the signed URL string.

    Raises the same exceptions `client.request` raises (APIError on the AV
    refusal / not-found status codes), which the caller routes through
    handle_error. A 200 envelope that still reports success=false is also
    surfaced as a CLIError so nothing silently returns an empty URL.
    """
    client = make_client(ctx)
    params = {"key": key, "name": name}
    if bucket:
        params["bucket"] = bucket
    result = asyncio.run(client.request("GET", "/api/v1/files/sign-get", params=params))
    if not result.get("success"):
        error = result.get("error")
        message = error.get("message") if isinstance(error, dict) else (error or "Download failed")
        raise CLIError(message)
    return result["data"]["url"]


@files_group.command("presign")
@click.option(
    "--file-name",
    required=True,
    help="Original filename. Used for Content-Disposition on download.",
)
@click.option(
    "--content-type",
    required=True,
    help="MIME type. Pinned into the presigned POST policy.",
)
@click.option(
    "--asset-id",
    required=True,
    help=(
        "Target asset id (entry/item/record). The backend runs a per-asset "
        "write-permission check and embeds x-amz-meta-assetid in the "
        "presigned POST policy."
    ),
)
@pass_context
def files_presign(ctx, file_name, content_type, asset_id):
    """Presign an S3 multipart POST envelope for one file.

    Prints the raw {uid, url, fields, bucket, expires_in} envelope as JSON.
    The caller is responsible for multipart-POSTing the file body to {url}
    with {fields} merged into the form data, and for any subsequent
    `mergeItemValues` write referencing the returned uid.
    """
    client = make_client(ctx)
    try:
        result = asyncio.run(
            client.request(
                "POST",
                "/api/v1/files/presign",
                json={
                    "file_name": file_name,
                    "content_type": content_type,
                    "asset_id": asset_id,
                },
            )
        )
    except Exception as e:
        handle_error(ctx, e)
        return

    # This command's deliverable is the envelope itself, so default to JSON.
    if ctx.json_mode:
        click.echo(format_json(result, compact=True))
    else:
        click.echo(format_json(result))

    if not result.get("success"):
        sys.exit(1)


@files_group.command("sign-get")
@click.option("--key", required=True, help="Stored S3 object key of the file.")
@click.option("--name", required=True, help="Filename for Content-Disposition on download.")
@click.option("--bucket", default=None, help="Source bucket. Defaults to the org bucket.")
@pass_context
def files_sign_get(ctx, key, name, bucket):
    """Print a short-lived signed download URL (URL only, no bytes).

    Use this when the URL is handed to another process; use `files download`
    to write the bytes to disk. The URL is AV-gated: an infected file or a
    pending scan is refused server-side.
    """
    try:
        url = _resolve_download_url(ctx, key, name, bucket)
    except Exception as e:
        handle_error(ctx, e)
        return

    if ctx.json_mode:
        click.echo(format_json({"success": True, "data": {"url": url}}, compact=True))
    else:
        click.echo(url)


@files_group.command("download")
@click.option("--key", required=True, help="Stored S3 object key of the file.")
@click.option("--name", required=True, help="Filename for Content-Disposition on download.")
@click.option("--bucket", default=None, help="Source bucket. Defaults to the org bucket.")
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Write the file bytes to this path.",
)
@click.option("--stdout", "to_stdout", is_flag=True, help="Stream the bytes to stdout instead.")
@click.option("--force", is_flag=True, help="Overwrite an existing --output file.")
@pass_context
def files_download(ctx, key, name, bucket, output, to_stdout, force):
    """Download a file's bytes to disk (--output) or stdout (--stdout).

    Resolves a signed URL (AV-gated) then streams the response in 8 KiB chunks,
    so large evidence files never buffer wholly in memory. Refuses to overwrite
    an existing --output file unless --force is given.
    """
    if bool(output) == bool(to_stdout):
        handle_error(ctx, CLIError("Provide exactly one of --output PATH or --stdout."))
        return

    # `exists()` resolves symlinks, so a *dangling* link at --output reports
    # False and the later open() would follow it and write the file's bytes to
    # wherever it points. Check for the link itself, not just its target.
    if output and (Path(output).exists() or Path(output).is_symlink()) and not force:
        handle_error(
            ctx, CLIError(f"Refusing to overwrite existing file: {output} (use --force).")
        )
        return

    try:
        url = _resolve_download_url(ctx, key, name, bucket)
    except Exception as e:
        handle_error(ctx, e)
        return

    import httpx

    verify_ssl = make_client(ctx).verify_ssl
    total = 0
    content_type = ""
    try:
        with httpx.stream("GET", url, timeout=60.0, verify=verify_ssl) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if to_stdout:
                for chunk in resp.iter_bytes(_DOWNLOAD_CHUNK):
                    sys.stdout.buffer.write(chunk)
                    total += len(chunk)
                sys.stdout.buffer.flush()
            else:
                # Evidence files carry compliance data; create them 0600 rather
                # than at the ambient umask (typically 0644, world-readable).
                fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    for chunk in resp.iter_bytes(_DOWNLOAD_CHUNK):
                        fh.write(chunk)
                        total += len(chunk)
    except Exception as e:
        handle_error(ctx, e)
        return

    # Report metadata on stderr for --stdout (keep stdout pure bytes); on stdout
    # for --output.
    if to_stdout:
        if not getattr(ctx, "quiet_mode", False):
            click.echo(f"Wrote {total} bytes ({content_type or 'unknown'}) to stdout", err=True)
        return
    if ctx.json_mode:
        click.echo(
            format_json(
                {
                    "success": True,
                    "data": {
                        "output": output,
                        "bytes_written": total,
                        "content_type": content_type,
                    },
                },
                compact=True,
            )
        )
    else:
        click.echo(f"Wrote {total} bytes ({content_type or 'unknown'}) to {output}")
