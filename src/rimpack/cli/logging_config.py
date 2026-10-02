"""Configure the CLI's namespace-scoped console and managed file logging."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

_LOGGER_NAME = "rimpack"
_LOG_FILE_NAME = "rimpack.log"
_MAX_LOG_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


def _warn_file_logging_unavailable(error: Exception) -> None:
    """Warn on stderr when managed file logging cannot be configured or used."""
    warning = (
        "rimpack: warning: managed file logging is unavailable; "
        f"continuing without it ({error})\n"
    )
    try:
        sys.stderr.write(warning)
        sys.stderr.flush()
    except (OSError, UnicodeError):
        pass


class _CliRichHandler(RichHandler):
    """Identify the Rich handler managed by Rimpack's CLI configuration."""


class _ManagedFileHandler(RotatingFileHandler):
    """Write plain UTF-8 DEBUG logs lazily and disable file output on I/O failure."""

    def __init__(self, path: Path) -> None:
        """Prepare a rotating handler without creating its directory or file."""
        super().__init__(
            path,
            mode="a",
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
            errors="backslashreplace",
            delay=True,
        )
        self.setLevel(logging.DEBUG)
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        self._file_logging_disabled = False

    def emit(self, record: logging.LogRecord) -> None:
        """Create the log directory on demand and suppress non-fatal I/O errors."""
        if self._file_logging_disabled:
            return
        try:
            if self.stream is None:
                Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
                self.stream = self._open()
            if self.shouldRollover(record):
                self.doRollover()
                if self.stream is None:
                    self.stream = self._open()
            if self.stream is not None:
                self.stream.write(self.format(record) + self.terminator)
                self.flush()
        except (OSError, UnicodeError) as error:
            self._disable_file_logging(error)

    def _disable_file_logging(self, error: OSError | UnicodeError) -> None:
        """Warn once on stderr and close the handler after an I/O failure."""
        self._file_logging_disabled = True
        try:
            self.close()
        except (OSError, UnicodeError):
            pass
        _warn_file_logging_unavailable(error)


def managed_log_path() -> Path:
    """Return the managed log path, independent of CLI configuration selection."""
    return Path.home() / ".rimpack" / "logs" / _LOG_FILE_NAME


def _find_handler[T: logging.Handler](
    logger: logging.Logger, handler_type: type[T]
) -> T | None:
    """Find one already-attached CLI handler of the requested concrete type."""
    return next(
        (handler for handler in logger.handlers if isinstance(handler, handler_type)),
        None,
    )


def configure_cli_logging(verbose: bool) -> None:
    """Idempotently configure only the Rimpack logger namespace for the CLI."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console_handler = _find_handler(logger, _CliRichHandler)
    if console_handler is None:
        console_handler = _CliRichHandler(
            console=Console(stderr=True),
            show_time=False,
            show_path=False,
            markup=False,
        )
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console_handler)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)

    file_handler = _find_handler(logger, _ManagedFileHandler)
    if file_handler is None:
        try:
            file_handler = _ManagedFileHandler(managed_log_path())
        except (OSError, RuntimeError, ValueError) as error:
            _warn_file_logging_unavailable(error)
        else:
            logger.addHandler(file_handler)
