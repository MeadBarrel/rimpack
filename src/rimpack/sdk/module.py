"""Parse Rimpack module YAML into immutable records and internal references.

The YAML-facing ``*ModReferenced`` and ``*ModRecord`` classes preserve source
values and structure. Their ``reference`` properties produce internal identity
values; resolving those identities against installed mods, aliases, or the
modpack root is a later operation.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn

import yaml
from pydantic import (
    ConfigDict,
    FailFast,
    StrictStr,
    ValidationError,
    field_validator,
)
from pydantic.dataclasses import dataclass as validated_dataclass
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, Node, ScalarNode

from rimpack.sdk._validation import SelectByRequiredField

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_DECIMAL_PATTERN = re.compile(r"[0-9]+\Z")
_YAML_BOOL_PATTERN = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")
_YAML_INTEGER_PATTERN = re.compile(r"^[-+]?(?:0|[1-9][0-9]*(?:_[0-9]+)*)$")
_UINT64_MAX = 18_446_744_073_709_551_615
_UINT64_MAX_TEXT = str(_UINT64_MAX)


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
        """Validate and lowercase the value so equality and hashing are canonical."""
        object.__setattr__(self, "value", _validated_package_id(self.value).lower())


@dataclass(frozen=True)
class WidReference:
    """Internal Steam Workshop identity stored as its decimal text."""

    value: str


@dataclass(frozen=True)
class LocReference:
    """Internal local-mod location, still unresolved relative to a modpack root."""

    value: Path


@dataclass(frozen=True)
class AlsReference:
    """Internal alias identity, not yet resolved through alias definitions."""

    value: str


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
        significant_digits = value.lstrip("0")
        if len(significant_digits) > len(_UINT64_MAX_TEXT) or (
            len(significant_digits) == len(_UINT64_MAX_TEXT)
            and significant_digits > _UINT64_MAX_TEXT
        ):
            raise ValueError(f"Workshop ID must not exceed {_UINT64_MAX_TEXT}")
        return value

    @property
    def reference(self) -> WidReference:
        """Return an internal Workshop identity for this source ID."""
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
class _AlsRecordBase:
    """Shared alias-name field and conversion for sibling YAML record types."""

    als: StrictStr

    @field_validator("als")
    @classmethod
    def _validate_als(cls, value: str) -> str:
        """Require an alias identifier and preserve its source spelling."""
        return _validated_identifier(value, "alias name")

    @property
    def reference(self) -> AlsReference:
        """Return an internal identity for this unresolved alias name."""
        return AlsReference(self.als)


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class PidModReferenced(_PidRecordBase):
    """Reference-only YAML mapping such as ``{pid: package.id}``."""


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class WidModReferenced(_WidRecordBase):
    """Reference-only YAML mapping such as ``{wid: 123456789}``."""


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class LocModReferenced(_LocRecordBase):
    """Reference-only YAML mapping whose path remains unresolved."""


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class AlsModReferenced(_AlsRecordBase):
    """Reference-only YAML mapping naming an alias."""


ReferencedModRecord = (
    PidModReferenced | WidModReferenced | LocModReferenced | AlsModReferenced
)
ReferencedModRecords = Annotated[
    tuple[Annotated[ReferencedModRecord, SelectByRequiredField()], ...],
    FailFast(),
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


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class AlsModRecord(_AlsRecordBase, ModOrderingConstraints):
    """Full YAML module entry identified by an alias name."""


ModRecord = PidModRecord | WidModRecord | LocModRecord | AlsModRecord
ModRecords = Annotated[
    tuple[Annotated[ModRecord, SelectByRequiredField()], ...],
    FailFast(),
]


@validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class Module:
    """A named module and its ordered, immutable sequence of mod entries."""

    name: StrictStr
    mods: ModRecords

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Require a module identifier while preserving the source spelling."""
        return _validated_identifier(value, "module name")


class ModuleParseError(ValueError):
    """Describe invalid module YAML with a source path and logical location."""

    def __init__(
        self,
        path: Path,
        location: str,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        """Store the source location and a concise explanation of the failure."""
        self.path = path
        self.location = location
        self.message = message
        self.line = line
        self.column = column
        super().__init__(self.__str__())

    def __str__(self) -> str:
        """Render the file, optional one-based source position, and logical path."""
        source = str(self.path)
        if self.line is not None:
            source += f":{self.line}"
            if self.column is not None:
                source += f":{self.column}"
        return f"{source}: {self.location}: {self.message}"


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe loader with predictable scalar, duplicate-key, and merge semantics."""

    yaml_implicit_resolvers = {
        first: [
            (tag, pattern)
            for tag, pattern in resolvers
            if tag not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:int"}
        ]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        """Construct a mapping only after checking key uniqueness and merge use."""
        if not isinstance(node, MappingNode):
            raise ConstructorError(
                None, None, "expected a mapping node", node.start_mark
            )
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "YAML merge keys are not supported",
                    key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "unhashable mapping key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _construct_decimal_integer(loader: _UniqueKeySafeLoader, node: ScalarNode) -> int:
    """Construct explicit integer tags only when they use supported decimal syntax."""
    value = loader.construct_scalar(node)
    if _YAML_INTEGER_PATTERN.fullmatch(value) is None:
        raise ConstructorError(
            "while constructing a decimal integer",
            node.start_mark,
            "only decimal integer syntax is supported",
            node.start_mark,
        )
    try:
        return int(value.replace("_", ""), 10)
    except ValueError as error:
        raise ConstructorError(
            "while constructing a decimal integer",
            node.start_mark,
            "decimal integer exceeds the supported conversion size",
            node.start_mark,
        ) from error


def _reject_tagged_collection(_loader: _UniqueKeySafeLoader, node: Node) -> NoReturn:
    """Reject YAML set, ordered-map, and pair tags outside the module schema."""
    raise ConstructorError(
        "while constructing a module collection",
        node.start_mark,
        f"YAML collection tag {node.tag!r} is not supported",
        node.start_mark,
    )


def _construct_yaml_timestamp(
    loader: _UniqueKeySafeLoader, node: ScalarNode
) -> object:
    """Preserve SafeLoader timestamps while marking invalid dates as YAML errors."""
    try:
        return loader.construct_yaml_timestamp(node)
    except ValueError as error:
        raise ConstructorError(
            "while constructing a YAML timestamp",
            node.start_mark,
            f"invalid YAML timestamp: {error}",
            node.start_mark,
        ) from error


_UniqueKeySafeLoader.add_constructor(
    "tag:yaml.org,2002:int", _construct_decimal_integer
)
_UniqueKeySafeLoader.add_constructor(
    "tag:yaml.org,2002:timestamp", _construct_yaml_timestamp
)
for _tagged_collection in (
    "tag:yaml.org,2002:set",
    "tag:yaml.org,2002:omap",
    "tag:yaml.org,2002:pairs",
):
    _UniqueKeySafeLoader.add_constructor(_tagged_collection, _reject_tagged_collection)
_UniqueKeySafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", _YAML_BOOL_PATTERN, list("tTfF")
)
_UniqueKeySafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int", _YAML_INTEGER_PATTERN, list("-+0123456789")
)

def _raise_validation_error(path: Path, error: ValidationError) -> NoReturn:
    """Raise an aggregate validation error without raw input or branch ranking.

    The location is always ``$`` because one ``ValidationError`` may contain
    several relevant details. Branch-qualified Pydantic locations stay in the
    rendered message instead of being rewritten as source YAML coordinates.
    """
    details = error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    message = "\n".join(
        f"{tuple(detail['loc'])!r}: {detail['msg']} [{detail['type']}]"
        for detail in details
    ) or "Validation failed without structured error details"
    raise ModuleParseError(path, "$", message) from None


def _mapping_at(value: object, path: Path) -> dict[str, Any]:
    """Require a YAML root mapping with string keys for dataclass construction."""
    if not isinstance(value, dict):
        raise ModuleParseError(path, "$", "expected a YAML mapping")
    for key in value:
        if not isinstance(key, str):
            raise ModuleParseError(path, "$", "mapping keys must be strings")
    return value


def _has_recursive_container(value: object) -> bool:
    """Detect recursive list/mapping aliases while allowing shared acyclic values."""
    active: set[int] = set()
    complete: set[int] = set()

    def visit(container: object) -> bool:
        """Return whether this container reaches itself through nested values."""
        if not isinstance(container, (dict, list)):
            return False
        identity = id(container)
        if identity in active:
            return True
        if identity in complete:
            return False
        active.add(identity)
        children = container.values() if isinstance(container, dict) else container
        if any(visit(child) for child in children):
            return True
        active.remove(identity)
        complete.add(identity)
        return False

    return visit(value)


def _yaml_error(path: Path, error: yaml.YAMLError) -> ModuleParseError:
    """Convert a PyYAML error and any available mark into a parser error."""
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    message = getattr(error, "problem", None) or str(error).splitlines()[0]
    return ModuleParseError(
        path,
        "$",
        message,
        line=mark.line + 1 if mark is not None else None,
        column=mark.column + 1 if mark is not None else None,
    )


def parse_module_yaml(path: str | Path) -> Module:
    """Parse one UTF-8 module YAML file into a complete immutable Module.

    Local ``loc`` values stay unresolved and relative to their eventual
    modpack-root resolution step. Invalid input raises ``ModuleParseError``;
    no partial module is returned. Filesystem access errors are left as ``OSError``.
    """
    source_path = Path(path)
    try:
        source_text = source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ModuleParseError(
            source_path, "$", "module file is not valid UTF-8"
        ) from error

    try:
        documents = list(yaml.load_all(source_text, Loader=_UniqueKeySafeLoader))
    except yaml.YAMLError as error:
        raise _yaml_error(source_path, error) from error
    except RecursionError as error:
        raise ModuleParseError(source_path, "$", "YAML nesting is too deep") from error
    if len(documents) != 1:
        raise ModuleParseError(source_path, "$", "expected exactly one YAML document")
    document = documents[0]
    if document is None:
        raise ModuleParseError(
            source_path, "$", "module YAML document must not be empty"
        )
    try:
        contains_cycle = _has_recursive_container(document)
    except RecursionError as error:
        raise ModuleParseError(source_path, "$", "YAML nesting is too deep") from error
    if contains_cycle:
        raise ModuleParseError(
            source_path, "$", "recursive YAML aliases are not supported"
        )

    raw_module = _mapping_at(document, source_path)
    try:
        return Module(**raw_module)
    except ValidationError as error:
        _raise_validation_error(source_path, error)
    except TypeError as error:
        raise ModuleParseError(
            source_path, "$", "could not construct a module from the YAML mapping"
        ) from error
