"""CLI managed logging and quiet SDK logging-boundary tests."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest
from typer.testing import CliRunner

from rimpack.cli import app, logging_config
from rimpack.cli.logging_config import (
    _CliRichHandler,
    _ManagedFileHandler,
    configure_cli_logging,
)
from rimpack.cli.setup import SetupCancelled, SetupOutcome
from rimpack.sdk import config as sdk_config
from rimpack.sdk import installation_discovery, modabout, module


@pytest.fixture(autouse=True)
def isolate_cli_handlers():
    """Remove handlers installed by CLI tests and restore namespace settings."""
    logger = logging.getLogger("rimpack")
    old_level = logger.level
    old_propagate = logger.propagate
    yield
    for handler in tuple(logger.handlers):
        if isinstance(handler, (_CliRichHandler, _ManagedFileHandler)):
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(old_level)
    logger.propagate = old_propagate


def test_cli_global_verbose_help_is_inert_and_options_stay_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose verbose globally while ensuring help never creates managed logs."""
    log_path = tmp_path / ".rimpack" / "logs" / "rimpack.log"
    monkeypatch.setattr(logging_config, "managed_log_path", lambda: log_path)
    runner = CliRunner()

    root_help = runner.invoke(app, ["--help"])
    setup_help = runner.invoke(app, ["--verbose", "setup", "--help"])
    wrong_position = runner.invoke(app, ["setup", "--verbose"])

    assert root_help.exit_code == setup_help.exit_code == 0
    assert "--verbose" in root_help.output
    assert wrong_position.exit_code == 2
    assert not log_path.exists()
    assert not log_path.parent.exists()


def test_console_threshold_file_capture_and_idempotent_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Show warnings by default, DEBUG on request, and always persist DEBUG."""
    log_path = tmp_path / ".rimpack" / "logs" / "rimpack.log"
    monkeypatch.setattr(logging_config, "managed_log_path", lambda: log_path)
    logger = logging.getLogger("rimpack.test_logging")

    configure_cli_logging(verbose=False)
    initial_handlers = tuple(logging.getLogger("rimpack").handlers)
    configure_cli_logging(verbose=False)
    assert tuple(logging.getLogger("rimpack").handlers) == initial_handlers

    logger.debug("default-hidden-debug")
    logger.warning("default-visible-warning")
    default_console = capfd.readouterr().err
    assert "default-visible-warning" in default_console
    assert "default-hidden-debug" not in default_console
    assert log_path.exists()
    assert "default-hidden-debug" in log_path.read_text(encoding="utf-8")
    assert "default-visible-warning" in log_path.read_text(encoding="utf-8")
    assert "\x1b[" not in log_path.read_text(encoding="utf-8")

    configure_cli_logging(verbose=True)
    logger.debug("verbose-visible-debug")
    verbose_console = capfd.readouterr().err
    assert "verbose-visible-debug" in verbose_console
    handlers = logging.getLogger("rimpack").handlers
    console = next(
        handler for handler in handlers if isinstance(handler, _CliRichHandler)
    )
    assert console.level == logging.DEBUG
    assert log_path.read_text(encoding="utf-8").count("verbose-visible-debug") == 1


def test_cli_logs_are_independent_of_selected_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persist lifecycle context under the home log path, not --config."""
    log_path = tmp_path / "home" / ".rimpack" / "logs" / "rimpack.log"
    config_path = tmp_path / "alternate" / "settings.yml"
    monkeypatch.setattr(logging_config, "managed_log_path", lambda: log_path)
    monkeypatch.setattr("rimpack.cli.terminal_is_usable", lambda: True)
    captured: list[str | None] = []

    def fake_setup(config: str | Path | None, ui: object) -> SetupOutcome:
        """Capture CLI config selection without performing setup I/O."""
        captured.append(str(config) if config is not None else None)
        return SetupOutcome(config_path, "declined")

    monkeypatch.setattr("rimpack.cli.run_setup", fake_setup)
    result = CliRunner().invoke(app, ["--config", str(config_path), "setup"])

    assert result.exit_code == 0
    assert captured == [str(config_path)]
    assert log_path.exists()
    assert "Starting setup command" in log_path.read_text(encoding="utf-8")
    assert "status declined" in log_path.read_text(encoding="utf-8")
    assert not config_path.exists()


def test_cancelled_setup_logs_without_changing_selected_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record setup cancellation while leaving an uncreated settings file alone."""
    log_path = tmp_path / ".rimpack" / "logs" / "rimpack.log"
    config_path = tmp_path / "profile" / "settings.yml"
    monkeypatch.setattr(logging_config, "managed_log_path", lambda: log_path)
    monkeypatch.setattr("rimpack.cli.terminal_is_usable", lambda: True)

    def cancel_setup(config: str | Path | None, ui: object) -> NoReturn:
        """Simulate the typed cancellation raised by an interactive prompt."""
        raise SetupCancelled()

    monkeypatch.setattr("rimpack.cli.run_setup", cancel_setup)
    result = CliRunner().invoke(app, ["--config", str(config_path), "setup"])

    assert result.exit_code == 130
    assert not config_path.exists()
    log = log_path.read_text(encoding="utf-8")
    assert "Starting setup command" in log
    assert "Setup command cancelled" in log


def test_file_rotation_retains_only_three_backups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotate plain text at the configured threshold and keep three backups."""
    log_path = tmp_path / ".rimpack" / "logs" / "rimpack.log"
    monkeypatch.setattr(logging_config, "managed_log_path", lambda: log_path)
    configure_cli_logging(verbose=False)
    handler = next(
        handler
        for handler in logging.getLogger("rimpack").handlers
        if isinstance(handler, _ManagedFileHandler)
    )
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3
    handler.maxBytes = 256

    logger = logging.getLogger("rimpack.test_rotation")
    for index in range(30):
        logger.debug("rotation-record-%02d %s", index, "x" * 80)
    handler.flush()

    backups = tuple(log_path.parent.glob("rimpack.log.*"))
    assert len(backups) == 3
    assert "rotation-record-29" in log_path.read_text(encoding="utf-8")
    assert all(
        "\x1b[" not in path.read_text(encoding="utf-8")
        for path in (log_path, *backups)
    )


def test_unavailable_log_directory_warns_once_without_stopping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Continue logging to stderr when the managed path cannot be initialized."""
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("block", encoding="utf-8")
    log_path = blocking_file / "rimpack.log"
    monkeypatch.setattr(logging_config, "managed_log_path", lambda: log_path)
    configure_cli_logging(verbose=False)
    logger = logging.getLogger("rimpack.test_logging_failure")

    logger.debug("first best-effort event")
    logger.debug("later best-effort event")

    error_output = capfd.readouterr().err
    assert "managed file logging is unavailable" in error_output
    assert error_output.count("managed file logging is unavailable") == 1
    assert blocking_file.is_file()


@pytest.mark.parametrize("failure_stage", ["home resolution", "handler construction"])
def test_cli_continues_when_file_logging_setup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    """Keep setup usable when resolving or constructing managed file logging fails."""
    if failure_stage == "home resolution":
        def fail_home_lookup() -> Path:
            """Simulate Python being unable to determine a home directory."""
            raise RuntimeError("home directory unavailable")

        monkeypatch.setattr(logging_config, "managed_log_path", fail_home_lookup)
    else:
        class FailingFileHandler(_ManagedFileHandler):
            """Raise during construction to model an unavailable file handler."""

            def __init__(self, path: Path) -> None:
                """Raise the expected initialization error without opening a file."""
                raise OSError("file handler initialization failed")

        monkeypatch.setattr(
            logging_config, "_ManagedFileHandler", FailingFileHandler
        )

    monkeypatch.setattr("rimpack.cli.terminal_is_usable", lambda: False)
    config_path = tmp_path / "alternate" / "settings.yml"
    result = CliRunner().invoke(app, ["--config", str(config_path), "setup"])

    assert result.exit_code == 1
    assert "managed file logging is unavailable" in result.output
    assert "Setup requires interactive terminal input" in result.output
    assert not config_path.exists()
    assert not any(
        isinstance(handler, _ManagedFileHandler)
        for handler in logging.getLogger("rimpack").handlers
    )


def test_sdk_boundaries_log_context_without_source_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Capture concise I/O context without leaking YAML or XML source values."""
    secret = "PRIVATE_SOURCE_CONTENT_74c23"
    config_path = tmp_path / "settings.yml"
    config_path.write_text(f"rimworld_path: {secret}\n", encoding="utf-8")
    module_path = tmp_path / "module.yml"
    module_path.write_text(f"name: {secret}\nmods: []\n", encoding="utf-8")
    about_path = tmp_path / "About.xml"
    about_path.write_text(
        "<ModMetaData><packageId>source.package</packageId>"
        f"<name>{secret}</name></ModMetaData>",
        encoding="utf-8",
    )
    monkeypatch.setattr(installation_discovery, "_is_windows", lambda: False)
    caplog.set_level(logging.DEBUG, logger="rimpack")

    sdk_config.parse_config_yaml(config_path)
    module.parse_module_yaml(module_path)
    modabout.parse_about_xml(about_path)
    assert installation_discovery.discover_rimworld_steam_installations() == ()

    messages = [record.getMessage() for record in caplog.records]
    assert any("Reading settings file" in message for message in messages)
    assert any("Reading module file" in message for message in messages)
    assert any("Reading About.xml file" in message for message in messages)
    assert any("explicit Steam RimWorld" in message for message in messages)
    assert all(secret not in message for message in messages)


def test_sdk_import_does_not_configure_logging() -> None:
    """Verify a fresh SDK import leaves root and Rimpack loggers untouched."""
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    script = (
        "import logging\n"
        "root = logging.getLogger()\n"
        "root_state = (root.level, tuple(root.handlers))\n"
        "import rimpack.sdk.config\n"
        "import rimpack.sdk.module\n"
        "import rimpack.sdk.modabout\n"
        "import rimpack.sdk.installation_discovery\n"
        "namespace = logging.getLogger('rimpack')\n"
        "assert (root.level, tuple(root.handlers)) == root_state\n"
        "assert namespace.level == logging.NOTSET\n"
        "assert not namespace.handlers\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
