"""Shared CLI context object."""

from typing import Optional

import click

from upscaler_cli.profile import DEFAULT_PROFILE


class Context:
    """Shared context object passed to all commands."""

    def __init__(self):
        self.json_mode: bool = False
        self.quiet_mode: bool = False
        self.verbose: bool = False
        self.server_url: Optional[str] = None
        self.profile: str = DEFAULT_PROFILE


pass_context = click.make_pass_decorator(Context, ensure=True)
