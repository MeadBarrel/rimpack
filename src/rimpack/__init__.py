"""Rimpack package and lazily loaded command-line entry point."""


def main() -> None:
    """Import and invoke the CLI application only when the console script runs."""
    from rimpack.cli import app

    app()
