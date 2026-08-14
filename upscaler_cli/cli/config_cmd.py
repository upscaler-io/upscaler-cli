"""CLI config command for persistent settings (per profile)."""

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.config import VALID_KEYS, CLIConfig


@click.group(
    "config",
    help="Manage persistent CLI settings in ~/.upscaler/profiles/{profile}/config.json.",
)
def config_group():
    pass


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@pass_context
def config_set(ctx, key, value):
    """Set a config value on the active profile."""
    try:
        config = CLIConfig(profile=ctx.profile)
        config.set(key, value)
        click.echo(f"[{ctx.profile}] {key} = {value}")
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@config_group.command("get")
@click.argument("key")
@pass_context
def config_get(ctx, key):
    """Get a config value from the active profile."""
    if key not in VALID_KEYS:
        click.echo(
            f"Unknown config key: {key}. Valid keys: {', '.join(sorted(VALID_KEYS))}",
            err=True,
        )
        raise SystemExit(1)
    config = CLIConfig(profile=ctx.profile)
    value = config.get(key)
    click.echo(value if value else "")
