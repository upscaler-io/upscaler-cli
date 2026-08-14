"""`upscaler profile` command group: list, current, set-default, delete."""

import json
import shutil

import click

from upscaler_cli.cli.context import pass_context
from upscaler_cli.profile import (
    DEFAULT_PROFILE,
    get_profile_dir,
    list_profiles,
    profiles_root,
    save_default_profile,
    validate_profile,
)


@click.group("profile", help="Manage CLI profiles (separate auth + config buckets).")
def profile_group():
    pass


@profile_group.command("list")
@pass_context
def profile_list(ctx):
    """List profiles on disk and mark the active one."""
    from upscaler_cli.auth.token_store import TokenStore
    from upscaler_cli.config import CLIConfig

    names = list_profiles()
    # Surface the active profile even if it has no dir yet.
    if ctx.profile not in names:
        names = sorted({*names, ctx.profile})

    rows = []
    for name in names:
        config = CLIConfig(profile=name)
        store = TokenStore(profile=name)
        authed = (config.config_dir / TokenStore.TOKEN_FILE).exists()
        rows.append({
            "name": name,
            "active": name == ctx.profile,
            "authenticated": authed,
            "server_url": config.resolve_server_url(),
            "dir": str(store.config_dir),
        })

    if ctx.json_mode:
        click.echo(json.dumps({"active": ctx.profile, "profiles": rows}))
        return

    if not rows:
        click.echo("No profiles found.")
        return

    width = max(len(r["name"]) for r in rows)
    for r in rows:
        marker = "*" if r["active"] else " "
        auth = "auth" if r["authenticated"] else "    "
        click.echo(f" {marker} {r['name']:<{width}}  {auth}  {r['server_url']}")


@profile_group.command("current")
@pass_context
def profile_current(ctx):
    """Print the active profile name."""
    if ctx.json_mode:
        click.echo(json.dumps({"profile": ctx.profile}))
    else:
        click.echo(ctx.profile)


@profile_group.command("set-default")
@click.argument("name")
@pass_context
def profile_set_default(ctx, name):
    """Save NAME as the default profile in ~/.upscaler/default_profile."""
    try:
        validate_profile(name)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    path = save_default_profile(name)
    known = name in list_profiles()

    if ctx.json_mode:
        click.echo(json.dumps({
            "success": True,
            "default": name,
            "path": str(path),
            "profile_exists": known,
        }))
        return

    click.echo(f"Default profile set to '{name}'.")
    if not known:
        click.echo(
            f"Note: profile '{name}' has no data yet; "
            f"run 'upscaler --profile {name} login' to authenticate it."
        )


@profile_group.command("delete")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@pass_context
def profile_delete(ctx, name, yes):
    """Delete a profile and all its auth + config state.

    The 'prod' profile cannot be deleted (it's the default).
    """
    try:
        validate_profile(name)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    if name == DEFAULT_PROFILE:
        click.echo(f"Refusing to delete the default profile '{DEFAULT_PROFILE}'.", err=True)
        raise SystemExit(1)

    target = get_profile_dir(name)
    if not target.exists():
        click.echo(f"Profile '{name}' does not exist at {target}.", err=True)
        raise SystemExit(1)

    if not yes and not ctx.json_mode:
        click.confirm(
            f"Delete profile '{name}' and all of its data at {target}?",
            abort=True,
        )

    shutil.rmtree(target)

    if ctx.json_mode:
        click.echo(json.dumps({"success": True, "deleted": name}))
    else:
        click.echo(f"Deleted profile '{name}'.")


# Surface the profiles root for help / debugging.
@profile_group.command("path")
@pass_context
def profile_path(ctx):
    """Print the on-disk path for the active profile."""
    path = str(get_profile_dir(ctx.profile))
    if ctx.json_mode:
        click.echo(json.dumps({"profile": ctx.profile, "path": path, "root": str(profiles_root())}))
    else:
        click.echo(path)
