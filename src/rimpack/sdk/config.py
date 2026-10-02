"""Read immutable SDK settings without discovery, writing, or CLI side effects."""

import errno
import stat
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Annotated, Any, NoReturn

from pydantic import BeforeValidator, ConfigDict, ValidationError
from pydantic.dataclasses import dataclass as validated_dataclass
from ruamel.yaml.error import YAMLError
from ruamel.yaml.reader import Reader, ReaderError

from rimpack.sdk._validation import (
    EmptyableList,
    validation_error_message,
    yaml_error_details,
)
from rimpack.sdk._yaml import load_yaml, yaml_load_failure
from rimpack.sdk.diagnostics import UnknownConfigFieldDiagnostic
from rimpack.sdk.errors import ParseError

_OPTIONAL_PATH_FIELDS = ("rimworld_path", "workshop_path", "data_path", "mods_path")


def _validate_path(value: object) -> object:
    """Require meaningful paths without NUL or Windows drive-relative ambiguity."""
    if not isinstance(value, (str, Path)):
        raise ValueError("path must be a string or Path")
    text = str(value)
    if not text or not text.strip():
        raise ValueError("path must be a nonempty, non-whitespace string")
    if "\x00" in text:
        raise ValueError("path must not contain NUL")
    path = Path(value)
    if path.drive and not path.root:
        raise ValueError(
            "drive-relative paths are not supported; "
            "use an absolute path such as C:/game or a relative path such as game"
        )
    return value


ConfigPath = Annotated[Path, BeforeValidator(_validate_path)]


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class Settings:
    """Explicit path overrides and ordered extra roots; loading resolves their paths.

    Direct Python construction validates paths but leaves their anchoring to the
    caller. Derived Data/Mods defaults never become explicit override fields.
    """

    rimworld_path: ConfigPath | None = None
    workshop_path: ConfigPath | None = None
    data_path: ConfigPath | None = None
    mods_path: ConfigPath | None = None
    extra_mod_paths: EmptyableList[ConfigPath] = ()

    @property
    def effective_data_path(self) -> Path | None:
        """Return the Data override or installation default, without filesystem I/O."""
        if self.data_path is not None:
            return self.data_path
        return self.rimworld_path / "Data" if self.rimworld_path is not None else None

    @property
    def effective_mods_path(self) -> Path | None:
        """Return the Mods override or installation default, without filesystem I/O."""
        if self.mods_path is not None:
            return self.mods_path
        return self.rimworld_path / "Mods" if self.rimworld_path is not None else None


@dataclass(frozen=True)
class ConfigLoadResult:
    """Validated settings, absolute lexical source path, and non-emitted warnings."""

    value: Settings
    path: Path
    diagnostics: tuple[UnknownConfigFieldDiagnostic, ...] = ()


class ConfigParseError(ParseError):
    """Describe invalid settings with a source path and logical location."""


def _expand_home(path: Path) -> Path:
    """Expand only current-user tilde forms, leaving named users literal."""
    if path.parts and path.parts[0] == "~":
        return Path.home().joinpath(*path.parts[1:])
    return path


def _absolute(path: Path) -> Path:
    """Validate and anchor a lexical path to cwd without canonicalizing symlinks."""
    _validate_path(path)
    return path if path.is_absolute() else Path.cwd() / path


def _actually_absent(path: Path) -> bool:
    """Distinguish missing entries from dangling symlinks, including ancestors.

    Called only after stat/read reports FileNotFoundError. Existing symlinks and
    Windows directory junctions must stat successfully before absence can be
    accepted; other OS errors propagate instead of masquerading as missing.
    """
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or candidate.is_junction():
            candidate.stat()
        return candidate != path
    return True


def _file_stat(path: Path) -> None:
    """Reject non-regular files before attempting a potentially blocking read."""
    if not stat.S_ISREG(path.stat().st_mode):
        raise OSError(errno.EINVAL, "configuration target must be a regular file", path)


def select_config_path(config: str | Path | None = None) -> Path:
    """Select one absolute settings path without creating or reading its contents.

    Existing filesystem types override suffix hints. Missing YAML-suffixed
    targets are files; other missing targets are directories. No fallback or
    merging occurs, and only current-user tilde forms are expanded.
    """
    if config is None:
        return _absolute(Path.home() / ".rimpack" / "settings.yml")
    _validate_path(config)
    target = _absolute(_expand_home(Path(config)))
    try:
        metadata = target.stat()
    except FileNotFoundError:
        if not _actually_absent(target):
            raise
        return (
            target
            if target.suffix.lower() in {".yml", ".yaml"}
            else target / "settings.yml"
        )
    if stat.S_ISDIR(metadata.st_mode):
        return target / "settings.yml"
    if stat.S_ISREG(metadata.st_mode):
        return target
    raise OSError(
        errno.EINVAL, "configuration target must be a file or directory", target
    )


def _yaml_error(path: Path, error: YAMLError) -> ConfigParseError:
    """Translate YAML source failures, retaining available one-based marks."""
    message, line, column = yaml_error_details(error)
    return ConfigParseError(path, "$", message, line=line, column=column)


def _raise_validation_error(path: Path, error: ValidationError) -> NoReturn:
    """Render aggregate Pydantic details without raw inputs, context, or URLs."""
    raise ConfigParseError(path, "$", validation_error_message(error)) from None


def _resolve_path(path: Path, parent: Path) -> Path:
    """Expand the current home and anchor values to the lexical source parent."""
    expanded = _expand_home(path)
    return expanded if expanded.is_absolute() else parent / expanded


def parse_config_yaml(path: str | Path) -> ConfigLoadResult:
    """Read one UTF-8 (optional BOM) safe YAML settings document.

    Blank/comment-only files mean empty settings. Unknown keys produce returned
    diagnostics, but their YAML syntax is still checked. Recognized invalid
    values fail the whole load; ordinary filesystem errors propagate unchanged.
    """
    source_path = _absolute(Path(path))
    _file_stat(source_path)
    try:
        source = source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConfigParseError(
            source_path, "$", "configuration file is not valid UTF-8"
        ) from error
    if all(
        not line.strip() or line.lstrip(" \t").startswith("#")
        for line in source.splitlines()
    ):
        # Keep reader-level character checks without parsing tab-indented
        # comment-only lines that this settings format accepts as blank.
        try:
            Reader(source)
        except ReaderError as error:
            raise _yaml_error(source_path, error) from error
        return ConfigLoadResult(Settings(), source_path)
    try:
        document = load_yaml(source)
    except YAMLError as error:
        raise _yaml_error(source_path, error) from error
    except (AssertionError, OverflowError, ValueError) as error:
        message = yaml_load_failure(error)
        if message is None:
            raise
        raise ConfigParseError(source_path, "$", message) from error
    except RecursionError as error:
        raise ConfigParseError(source_path, "$", "YAML nesting is too deep") from error
    if not isinstance(document, dict):
        raise ConfigParseError(source_path, "$", "expected a YAML mapping")
    recognized = {field.name for field in fields(Settings)}
    values: dict[str, Any] = {}
    diagnostics: list[UnknownConfigFieldDiagnostic] = []
    for key, value in document.items():
        if not isinstance(key, str):
            raise ConfigParseError(source_path, "$", "mapping keys must be strings")
        if key in recognized:
            values[key] = value
        else:
            diagnostics.append(UnknownConfigFieldDiagnostic(key))
    for field_name in _OPTIONAL_PATH_FIELDS:
        if field_name in values and values[field_name] is None:
            raise ConfigParseError(
                source_path,
                "$",
                f"{field_name} must be omitted; YAML null and blank values are invalid",
            )
    try:
        settings = Settings(**values)
    except ValidationError as error:
        _raise_validation_error(source_path, error)
    except RecursionError as error:
        raise ConfigParseError(source_path, "$", "YAML nesting is too deep") from error
    resolved: dict[str, Any] = {
        field.name: (
            tuple(_resolve_path(entry, source_path.parent) for entry in value)
            if isinstance(value, tuple)
            else _resolve_path(value, source_path.parent)
            if value is not None
            else None
        )
        for field in fields(Settings)
        for value in (getattr(settings, field.name),)
    }
    return ConfigLoadResult(Settings(**resolved), source_path, tuple(diagnostics))


def load_config(config: str | Path | None = None) -> ConfigLoadResult:
    """Select and parse settings; only an absent default means empty settings."""
    path = select_config_path(config)
    try:
        return parse_config_yaml(path)
    except FileNotFoundError:
        if config is not None:
            raise
        if not _actually_absent(path):
            raise
        return ConfigLoadResult(Settings(), path)
