"""Typer command-line application for Rimpack."""

from __future__ import annotations

import logging
import sys
from typing import Annotated

import typer

from rimpack.cli.logging_config import configure_cli_logging
from rimpack.cli.prompts import PromptToolkitUI
from rimpack.cli.setup import SetupCancelled, run_setup

logger = logging.getLogger(__name__)

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
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Show DEBUG log records on stderr.",
        ),
    ] = False,
) -> None:
    """Store global options and initialize CLI logging without loading settings."""
    configure_cli_logging(verbose)
    context.ensure_object(dict)
    context.obj["config"] = config
    context.obj["verbose"] = verbose


def terminal_is_usable() -> bool:
    """Return whether setup has interactive stdin and stdout terminal streams."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except AttributeError, OSError:
        return False


@app.command("setup")
def setup_command(context: typer.Context) -> None:
    """Interactively choose and validate RimWorld and Workshop source paths."""
    logger.debug("Starting setup command")
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
        outcome = run_setup(context.obj.get("config"), ui)
        logger.debug("Setup command finished with status %s", outcome.status)
    except SetupCancelled, KeyboardInterrupt, EOFError:
        logger.debug("Setup command cancelled")
        ui.show("Setup cancelled; no settings were changed.", kind="warning")
        raise typer.Exit(code=130) from None
    except Exception as error:
        logger.debug("Setup command failed")
        ui.show(f"Setup failed: {error}", kind="error")
        raise typer.Exit(code=1) from error


def main() -> None:
    """Load and invoke Typer only when the installed CLI entry point is called."""
    app()
