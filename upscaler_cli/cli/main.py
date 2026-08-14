"""Root Click group for the Upscaler CLI.

Entry point: upscaler = upscaler_cli.cli.main:cli

Global flags:
    --json / --no-json   Output structured JSON to stdout. Default from
                         $UPSCALER_OUTPUT (set to 'json' to make JSON the
                         shell-wide default; --no-json forces human output
                         when the env var is set). Passing --json explicitly
                         is always accepted and idempotent, even when the env
                         var already makes JSON the default.
    --verbose            Log HTTP request/response to stderr
    --server             Override REST API server URL
    --profile NAME       Use a named profile (auth + config). Default: prod.
                         Overrides $UPSCALER_PROFILE.
    --version            Print package version
"""

import os
import sys

import click

import upscaler_cli
from upscaler_cli.cli.context import Context, pass_context  # noqa: F401
from upscaler_cli.profile import resolve_profile

AGENT_SKILLS_URL = "https://github.com/upscaler-io/upscaler-skills"
_VERSION_MESSAGE = (
    f"%(prog)s %(version)s\n"
    f"Agent skills: {AGENT_SKILLS_URL}/tree/{upscaler_cli.RECOMMENDED_SKILLS_REF}"
)


def _default_json_mode():
    return os.environ.get("UPSCALER_OUTPUT", "").lower() == "json"


# Global options that GlobalFlagGroup accepts in any position. Boolean flags
# take no value; value options carry the following token (or the --opt=value
# form).
_GLOBAL_BOOL_FLAGS = frozenset({"--json", "--no-json", "--quiet", "-q", "--verbose", "-v"})
_GLOBAL_VALUE_OPTS = frozenset({"--server", "--profile"})


def _collect_value_taking_opts(command, acc):
    """Recursively collect every value-taking (non-flag) option string.

    A flag's value position (e.g. the `--quiet` in `--title --quiet`) must not
    be hoisted, so the hoister needs to know which option spellings take a value.
    Walks the subcommand tree once per invocation; cheap (commands are already
    imported by the time the root group parses).
    """
    for param in getattr(command, "params", []):
        if isinstance(param, click.Option) and not param.is_flag and not param.count:
            acc.update(param.opts)
            acc.update(param.secondary_opts)
    if isinstance(command, click.Group):
        for sub in command.commands.values():
            _collect_value_taking_opts(sub, acc)


def _value_taking_subcommand_opts(group):
    """Value-taking option spellings across all subcommands (not the root globals)."""
    acc = set()
    for sub in group.commands.values():
        _collect_value_taking_opts(sub, acc)
    return acc


def _hoist_global_options(args, value_taking_opts=frozenset()):
    """Move the CLI's global options to the front of the argument list.

    Click only consumes group-level options that appear before the subcommand,
    so `upscaler health --json` fails with "No such option" even though
    `upscaler --json health` works. Agents and people routinely place `--json`
    (and friends) after the subcommand, so the root group hoists the known
    global options to the front before Click parses the command.

    Scanning stops at `--`, the end-of-options marker, leaving genuinely
    positional arguments after it untouched. A token that sits in the value
    position of a subcommand option that takes a value (its name is in
    `value_taking_opts`) is left untouched, so e.g. `--title "--quiet"` keeps
    `--quiet` as the title's value instead of hoisting it as a global flag.
    """
    hoisted = []
    rest = []
    i = 0
    n = len(args)
    while i < n:
        tok = args[i]
        if tok == "--":
            rest.extend(args[i:])
            break
        # A value-taking option shields the next token: it is that option's
        # value, even if it spells a global flag.
        if i > 0 and args[i - 1] in value_taking_opts:
            rest.append(tok)
            i += 1
        elif tok in _GLOBAL_BOOL_FLAGS:
            hoisted.append(tok)
            i += 1
        elif tok in _GLOBAL_VALUE_OPTS:
            hoisted.append(tok)
            if i + 1 < n:
                hoisted.append(args[i + 1])
                i += 2
            else:
                i += 1
        elif "=" in tok and tok.split("=", 1)[0] in _GLOBAL_VALUE_OPTS:
            hoisted.append(tok)
            i += 1
        else:
            rest.append(tok)
            i += 1
    return hoisted + rest


class GlobalFlagGroup(click.Group):
    """Root group that accepts the CLI's global options in any position.

    Global flags are defined on this group, which by default Click only parses
    before the subcommand. Hoisting them (see _hoist_global_options) makes
    `upscaler list entries --json` behave like `upscaler --json list entries`.
    """

    def parse_args(self, ctx, args):
        value_opts = _value_taking_subcommand_opts(self)
        return super().parse_args(ctx, _hoist_global_options(args, value_opts))


@click.group(cls=GlobalFlagGroup, epilog=f"Agent skills for Upscaler: {AGENT_SKILLS_URL}")
@click.option(
    "--json/--no-json",
    "json_mode",
    default=_default_json_mode,
    help="Output structured JSON. Default from $UPSCALER_OUTPUT=json.",
)
@click.option(
    "--quiet",
    "-q",
    "quiet_mode",
    is_flag=True,
    help="Print only the resulting id(s); suppress full payload/schema echo.",
)
@click.option("--verbose", "-v", is_flag=True, help="Log HTTP details to stderr.")
@click.option("--server", default=None, help="Override REST API server URL.")
@click.option(
    "--profile",
    default=None,
    help="Profile name (own auth + config). Default: prod. " "Overrides $UPSCALER_PROFILE.",
)
@click.version_option(
    version=upscaler_cli.__version__, prog_name="upscaler", message=_VERSION_MESSAGE
)
@click.pass_context
def cli(ctx, json_mode, quiet_mode, verbose, server, profile):
    """Upscaler CLI: search, retrieve, and manage documents, records, and workflows.

    Global flags (--json, --quiet, --profile, --server, --verbose) are options on
    this top-level group but are accepted in any position, so both
    `upscaler --json list entries ...` and `upscaler list entries --json` work.
    """
    ctx.ensure_object(Context)
    ctx.obj.json_mode = json_mode
    ctx.obj.quiet_mode = quiet_mode
    ctx.obj.verbose = verbose
    ctx.obj.server_url = server
    try:
        ctx.obj.profile = resolve_profile(profile)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@cli.command("health")
@click.pass_context
def health(ctx):
    """Check if the Upscaler API server is reachable.

    Examples:
        upscaler health
        upscaler --json health
        upscaler --server https://custom.example.com health
    """
    import asyncio
    import json

    import httpx

    from upscaler_cli.config import CLIConfig

    config = CLIConfig(profile=ctx.obj.profile)
    server_url = config.resolve_server_url(ctx.obj.server_url)
    verify_ssl = config.resolve_verify_ssl()
    if not server_url:
        click.echo(
            "Server URL not configured. " "Use --server or: upscaler config set server_url <url>",
            err=True,
        )
        sys.exit(1)

    try:
        response = asyncio.run(
            httpx.AsyncClient(verify=verify_ssl, timeout=5.0).get(f"{server_url}/health")
        )
        data = response.json()
        if ctx.obj.json_mode:
            click.echo(
                json.dumps(
                    {
                        "success": True,
                        "status": data.get("status"),
                        "server": server_url,
                    }
                )
            )
        else:
            click.echo(f"Server: {server_url}")
            click.echo(f"Status: {data.get('status', 'unknown')}")
    except Exception as e:
        if ctx.obj.json_mode:
            click.echo(
                json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                        "server": server_url,
                    }
                ),
                err=True,
            )
        else:
            click.echo(f"Server: {server_url}")
            click.echo(f"Status: unreachable ({e})", err=True)
        sys.exit(1)


# Register subcommands
from upscaler_cli.cli.asset import asset_group  # noqa: E402
from upscaler_cli.cli.auth import login, logout, refresh, status  # noqa: E402
from upscaler_cli.cli.automation import automation_group  # noqa: E402
from upscaler_cli.cli.comment import comment_group  # noqa: E402
from upscaler_cli.cli.completions import completions  # noqa: E402
from upscaler_cli.cli.config_cmd import config_group  # noqa: E402
from upscaler_cli.cli.entry import entry_group  # noqa: E402
from upscaler_cli.cli.files import files_group  # noqa: E402
from upscaler_cli.cli.framework import framework_group  # noqa: E402
from upscaler_cli.cli.get import get_asset  # noqa: E402
from upscaler_cli.cli.hierarchy import hierarchy  # noqa: E402
from upscaler_cli.cli.list_cmd import list_group  # noqa: E402
from upscaler_cli.cli.profile_cmd import profile_group  # noqa: E402
from upscaler_cli.cli.recover import recover_cmd  # noqa: E402
from upscaler_cli.cli.search import search  # noqa: E402
from upscaler_cli.cli.todo import todo_group  # noqa: E402

cli.add_command(login)
cli.add_command(refresh)
cli.add_command(status)
cli.add_command(logout)
cli.add_command(search)
cli.add_command(get_asset)
cli.add_command(hierarchy)
cli.add_command(list_group)
cli.add_command(todo_group)
cli.add_command(entry_group)
cli.add_command(files_group)
cli.add_command(asset_group)
cli.add_command(automation_group)
cli.add_command(framework_group)
cli.add_command(comment_group)
cli.add_command(recover_cmd)
cli.add_command(config_group)
cli.add_command(profile_group)
cli.add_command(completions)
