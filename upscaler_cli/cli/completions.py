"""Shell completion script generator."""

import click


@click.command("completions")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completions(shell):
    """Generate shell completion script for bash, zsh, or fish.

    Install completions:
        eval "$(upscaler completions bash)"
        eval "$(upscaler completions zsh)"
        upscaler completions fish | source
    """
    import os

    env_var = "_UPSCALER_COMPLETE"
    shell_map = {
        "bash": "bash_source",
        "zsh": "zsh_source",
        "fish": "fish_source",
    }

    os.environ[env_var] = shell_map[shell]
    try:
        from upscaler_cli.cli.main import cli

        cli(standalone_mode=False)
    except SystemExit:
        pass
    finally:
        os.environ.pop(env_var, None)
