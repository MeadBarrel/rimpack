"""Typer command-line application for Rimpack."""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from rimpack.cli.prompts import PromptToolkitUI
from rimpack.cli.setup import SetupCancelled, run_setup

app = typer.Typer(
    name="rimpack",
    help="Configure and inspect RimWorld modpack settings.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root(
    context: typer.Context,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            metavar="PATH",
            help="Select a settings file or configuration directory.",
        ),
    ] = None,
) -> None:
    """Store the global config argument without inspecting the filesystem."""
    context.ensure_object(dict)
    context.obj["config"] = config


def terminal_is_usable() -> bool:
    """Return whether setup has interactive stdin and stdout terminal streams."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except AttributeError, OSError:
        return False


@app.command("setup")
def setup_command(context: typer.Context) -> None:
    """Interactively choose and validate RimWorld and Workshop source paths."""
    ui = PromptToolkitUI()
    if not terminal_is_usable():
        ui.show(
            "Setup requires interactive terminal input and output. Run "
            "`rimpack setup` in a terminal, or create the selected settings YAML "
            "manually.",
            kind="error",
        )
        raise typer.Exit(code=1)

    try:
        run_setup(context.obj.get("config"), ui)
    except SetupCancelled, KeyboardInterrupt, EOFError:
        ui.show("Setup cancelled; no settings were changed.", kind="warning")
        raise typer.Exit(code=130) from None
    except Exception as error:
        ui.show(f"Setup failed: {error}", kind="error")
        raise typer.Exit(code=1) from error


def main() -> None:
    """Load and invoke Typer only when the installed CLI entry point is called."""
    app()
