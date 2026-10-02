"""Parse Rimpack module YAML into immutable records and internal references.

The YAML-facing ``*ModReferenced`` and ``*ModRecord`` classes preserve source
values and structure. Their ``reference`` properties produce internal identity
values; resolving those identities against installed mods or the modpack root
is a later operation.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn

from pydantic import ConfigDict, StrictStr, ValidationError, field_validator
from pydantic.dataclasses import dataclass as validated_dataclass
from ruamel.yaml.error import YAMLError

from rimpack.sdk._validation import (
    EmptyableList,
    SelectByRequiredField,
    validation_error_message,
    yaml_error_details,
)
from rimpack.sdk._yaml import load_yaml, yaml_load_failure
from rimpack.sdk.errors import ParseError

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_DECIMAL_PATTERN = re.compile(r"[0-9]+\Z")
_UINT64_MAX = 18_446_744_073_709_551_615
_UINT64_MAX_TEXT = str(_UINT64_MAX)

logger = logging.getLogger(__name__)


def _validated_package_id(value: object) -> str:
    """Require a nonempty ASCII package ID without whitespace.

    Source records retain the returned spelling; ``PidReference`` separately
    lowercases it to provide case-insensitive value equality.
    """
    if not isinstance(value, str):
        raise TypeError("package ID must be a string")
    if (
        not value
        or not value.isascii()
        or any(character.isspace() for character in value)
    ):
        raise ValueError("package ID must be nonempty ASCII text without whitespace")
    return value


def _validated_identifier(value: object, description: str) -> str:
    """Require the project's ASCII identifier syntax and preserve its spelling."""
    if not isinstance(value, str):
        raise TypeError(f"{description} must be a string")
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{description} must match [A-Za-z_][A-Za-z0-9_]*")
    return value


def _validated_local_path(value: object) -> object:
    """Reject empty, whitespace-only, and NUL-containing path inputs."""
    if isinstance(value, Path):
        raw_value = str(value)
    elif isinstance(value, str):
        raw_value = value
    else:
        return value
    if not raw_value or not raw_value.strip():
        raise ValueError("local path must be a nonempty, non-whitespace string")
    if "\x00" in raw_value:
        raise ValueError("local path must not contain NUL")
    return value


@dataclass(frozen=True)
class PidReference:
    """Canonical internal package-ID identity, compared case-insensitively."""

    value: str

    def __post_init__(self) -> None:
        """Lowercase the trusted value so equality and hashing are canonical."""
        object.__setattr__(self, "value", self.value.lower())


@dataclass(frozen=True)
class WidReference:
    """Canonical Workshop identity without source-only leading zeros."""

    value: str

    def __post_init__(self) -> None:
        """Strip leading zeros so equal numeric IDs compare and hash alike."""
        object.__setattr__(self, "value", self.value.lstrip("0") or "0")


@dataclass(frozen=True)
class LocReference:
    """Internal local-mod location, still unresolved relative to a modpack root."""

    value: Path


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class _PidRecordBase:
    """Shared package-ID field and conversion for sibling YAML record types."""

    pid: StrictStr

    @field_validator("pid")
    @classmethod
    def _validate_pid(cls, value: str) -> str:
        """Validate a source package ID without changing its spelling."""
        return _validated_package_id(value)

    @property
    def reference(self) -> PidReference:
        """Return the canonical internal identity for this source package ID."""
        return PidReference(self.pid)


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class _WidRecordBase:
    """Shared Workshop-ID field and conversion for sibling YAML record types."""

    wid: StrictStr

    @field_validator("wid", mode="before")
    @classmethod
    def _validate_wid(cls, value: object) -> str:
        """Normalize positive uint64 IDs and preserve valid decimal string spelling."""
        if isinstance(value, bool):
            raise ValueError("Workshop ID must not be a boolean")
        if isinstance(value, int):
            if value < 1:
                raise ValueError("Workshop ID must be positive")
            if value > _UINT64_MAX:
                raise ValueError(f"Workshop ID must not exceed {_UINT64_MAX_TEXT}")
            return str(value)
        if not isinstance(value, str):
            raise ValueError(
                "Workshop ID must be a positive integer or decimal digit string"
            )
        if _DECIMAL_PATTERN.fullmatch(value) is None or not any(
            character != "0" for character in value
        ):
            raise ValueError("Workshop ID must be a positive decimal value")
        # Compare text rather than converting to int: quoted IDs may be heavily
        # zero-padded and exceed Python's integer-string conversion limit.
        significant_digits = value.lstrip("0")
        if len(significant_digits) > len(_UINT64_MAX_TEXT) or (
            len(significant_digits) == len(_UINT64_MAX_TEXT)
            and significant_digits > _UINT64_MAX_TEXT
        ):
            raise ValueError(f"Workshop ID must not exceed {_UINT64_MAX_TEXT}")
        return value

    @property
    def reference(self) -> WidReference:
        """Return a canonical identity while keeping the source ID unchanged."""
        return WidReference(self.wid)


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class _LocRecordBase:
    """Shared unresolved local-path field for sibling YAML record types."""

    loc: Path

    @field_validator("loc", mode="before")
    @classmethod
    def _validate_loc(cls, value: object) -> object:
        """Validate path text lexically without accessing the filesystem."""
        return _validated_local_path(value)

    @property
    def reference(self) -> LocReference:
        """Return this unresolved local path as an internal reference."""
        return LocReference(self.loc)


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class PidModReferenced(_PidRecordBase):
    """Reference-only YAML mapping such as ``{pid: package.id}``."""


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class WidModReferenced(_WidRecordBase):
    """Reference-only YAML mapping such as ``{wid: 123456789}``."""


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class LocModReferenced(_LocRecordBase):
    """Reference-only YAML mapping whose path remains unresolved."""


ReferencedModRecord = PidModReferenced | WidModReferenced | LocModReferenced
ReferencedModRecords = EmptyableList[
    Annotated[ReferencedModRecord, SelectByRequiredField()]
]


@validated_dataclass(
    frozen=True,
    kw_only=True,
    config=ConfigDict(extra="forbid"),
)
class ModOrderingConstraints:
    """Optional ordering constraints attached to one full module entry."""

    before: ReferencedModRecords = ()
    after: ReferencedModRecords = ()


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class PidModRecord(_PidRecordBase, ModOrderingConstraints):
    """Full YAML module entry identified by a RimWorld package ID."""


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class WidModRecord(_WidRecordBase, ModOrderingConstraints):
    """Full YAML module entry identified by a Steam Workshop ID."""


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class LocModRecord(_LocRecordBase, ModOrderingConstraints):
    """Full YAML module entry identified by an unresolved local path."""


ModRecord = PidModRecord | WidModRecord | LocModRecord
ModRecords = EmptyableList[Annotated[ModRecord, SelectByRequiredField()]]


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class Module:
    """A named module with an ordered, immutable mod sequence.

    ``mods`` defaults to an empty tuple. An exactly empty string is also accepted
    as an empty collection by the ``EmptyableList`` validation type.
    """

    name: StrictStr
    mods: ModRecords = ()

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Require a module identifier while preserving the source spelling."""
        return _validated_identifier(value, "module name")


class ModuleParseError(ParseError):
    """Describe invalid module YAML with a source path and logical location."""


def _raise_validation_error(path: Path, error: ValidationError) -> NoReturn:
    """Raise an aggregate validation error without raw input or branch ranking.

    The location is always ``$`` because one ``ValidationError`` may contain
    several relevant details. Branch-qualified Pydantic locations stay in the
    rendered message instead of being rewritten as source YAML coordinates.
    """
    raise ModuleParseError(path, "$", validation_error_message(error)) from None


def _mapping_at(value: object, path: Path) -> dict[str, Any]:
    """Require a YAML root mapping with string keys for dataclass construction."""
    if not isinstance(value, dict):
        raise ModuleParseError(path, "$", "expected a YAML mapping")
    for key in value:
        if not isinstance(key, str):
            raise ModuleParseError(path, "$", "mapping keys must be strings")
    return value


def _empty_yaml_document(source: str) -> bool:
    """Return whether the source contains only whitespace and whole-line comments."""
    return all(
        not line.strip() or line.lstrip().startswith("#")
        for line in source.splitlines()
    )


def _yaml_error(path: Path, error: YAMLError) -> ModuleParseError:
    """Convert a YAML source failure and any available mark to a parse error."""
    message, line, column = yaml_error_details(error)
    return ModuleParseError(path, "$", message, line=line, column=column)


def parse_module_yaml(path: str | Path) -> Module:
    """Parse one safe YAML module document into an immutable Module.

    Native YAML scalar types pass to schema validation. Missing, null, and empty
    collection fields become empty tuples; local ``loc`` values remain unresolved
    relative to their eventual modpack-root resolution step. Invalid input raises
    ``ModuleParseError``; filesystem access errors remain ``OSError`` subclasses.
    """
    source_path = Path(path)
    logger.debug("Reading module file %s", source_path)
    try:
        source_text = source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ModuleParseError(
            source_path, "$", "module file is not valid UTF-8"
        ) from error

    if _empty_yaml_document(source_text):
        raise ModuleParseError(
            source_path, "$", "module YAML document must not be empty"
        )

    try:
        document = load_yaml(source_text)
    except YAMLError as error:
        raise _yaml_error(source_path, error) from error
    except (AssertionError, OverflowError, ValueError) as error:
        message = yaml_load_failure(error)
        if message is None:
            raise
        raise ModuleParseError(source_path, "$", message) from error
    except RecursionError as error:
        raise ModuleParseError(source_path, "$", "YAML nesting is too deep") from error

    raw_module = _mapping_at(document, source_path)
    try:
        module = Module(**raw_module)
        logger.debug("Parsed module file %s", source_path)
        return module
    except ValidationError as error:
        _raise_validation_error(source_path, error)
    except RecursionError as error:
        raise ModuleParseError(source_path, "$", "YAML nesting is too deep") from error
    except TypeError as error:
        raise ModuleParseError(
            source_path, "$", "could not construct a module from the YAML mapping"
        ) from error
