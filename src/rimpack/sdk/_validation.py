"""Shared error formatting and Pydantic collection/union validation helpers.

``EmptyableList`` normalizes exactly blank strings for opted-in immutable tuple
fields. The selector inspects generated CoreSchemas to infer each union
variant's required input key, retaining branch schemas for validation and
serialization while rejecting shapes it cannot interpret safely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import UnionType
from typing import Annotated, Any, Union, cast, get_args, get_origin

from pydantic import BeforeValidator, FailFast, GetCoreSchemaHandler, ValidationError
from pydantic_core import CoreSchema, core_schema
from strictyaml import YAMLError


def validation_error_message(error: ValidationError) -> str:
    """Format aggregate validation details without inputs, context, or URLs.

    Preserve Pydantic's detail order and tuple locations, including branch
    qualifiers. These logical locations are not YAML source coordinates.
    """
    details = error.errors(
        include_url=False, include_context=False, include_input=False
    )
    return (
        "\n".join(
            f"{tuple(detail['loc'])!r}: {detail['msg']} [{detail['type']}]"
            for detail in details
        )
        or "Validation failed without structured error details"
    )


def yaml_error_details(error: YAMLError) -> tuple[str, int | None, int | None]:
    """Extract a YAML message and optional one-based line/column coordinates.

    Prefer the problem mark, falling back to the context mark. Reader failures
    may have neither; do not invent coordinates when no source mark exists.
    """
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    message = getattr(error, "problem", None) or str(error).splitlines()[0]
    return (
        message,
        mark.line + 1 if mark is not None else None,
        mark.column + 1 if mark is not None else None,
    )


def _empty_string_as_empty_collection(value: object) -> object:
    """Normalize an exactly empty string before validating a collection.

    Other values, including whitespace-only strings and ``None``, pass through
    unchanged so the collection validator can reject them normally.
    """
    return [] if isinstance(value, str) and value == "" else value


# Keep FailFast on the tuple schema before the outer input normalizer is applied.
type EmptyableList[T] = Annotated[
    tuple[T, ...],
    FailFast(),
    BeforeValidator(_empty_string_as_empty_collection),
]


@dataclass(frozen=True)
class _InputField:
    """Describe one generated dataclass field's accepted input shape."""

    name: str
    accepted_keys: frozenset[str]
    required: bool


@dataclass(frozen=True)
class _Branch:
    """Keep a generated branch schema beside its inferred input fields."""

    schema: CoreSchema
    cls: type[Any]
    fields: tuple[_InputField, ...]


@dataclass(frozen=True)
class _Identity:
    """Identify the unique required input field for one union branch."""

    branch: _Branch
    tag: str
    accepted_keys: frozenset[str]


def _mapping(value: object, description: str) -> Mapping[str, Any]:
    """Validate a CoreSchema node as a mapping with a stable error message."""
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected a Pydantic CoreSchema mapping for {description}")
    return value


def _is_required(field_schema: object) -> bool:
    """Infer field requiredness from generated default and validator wrappers.

    Pydantic places a field-level default outside ordinary field validators.
    Follow only known function wrappers: a default nested inside the value type
    does not make the dataclass field itself optional.
    """
    current = _mapping(field_schema, "dataclass field")
    while current.get("type") in {"function-before", "function-after", "function-wrap"}:
        current = _mapping(current.get("schema"), "field validator")
    return current.get("type") != "default"


def _accepted_keys(
    field: Mapping[str, Any], config: Mapping[str, Any]
) -> frozenset[str]:
    """Return the schema-configured input spellings accepted for a field.

    Simple string validation aliases, alias generators, and configured
    field-name acceptance are supported. Alias paths and choices are rejected
    because a value-aware selector cannot safely infer their input semantics.
    """
    name = field.get("name")
    if not isinstance(name, str):
        raise TypeError("Unsupported dataclass field without a string name")

    validation_alias = field.get("validation_alias")
    if validation_alias is None:
        return frozenset({name})
    if not isinstance(validation_alias, str):
        raise TypeError(
            f"Unsupported validation_alias for field {name!r}; "
            "only simple string aliases are supported"
        )

    validate_by_alias = config.get("validate_by_alias")
    if validate_by_alias is None:
        validate_by_alias = True
    validate_by_name = config.get("validate_by_name")
    if validate_by_name is None:
        validate_by_name = config.get("populate_by_name", False)

    names: set[str] = set()
    if validate_by_alias:
        names.add(validation_alias)
    if validate_by_name:
        names.add(name)
    if not names:
        raise TypeError(f"No supported input name is enabled for field {name!r}")
    return frozenset(names)


def _inspect_branch(schema: CoreSchema, handler: GetCoreSchemaHandler) -> _Branch:
    """Inspect a generated dataclass branch without replacing its schema.

    Only known definitions, reference, outer after-validator, dataclass,
    dataclass-args, and dataclass-field shapes are traversed. Wrappers that can
    transform input, non-forbid extra handling, and init-only fields are
    rejected because their accepted keys cannot be inferred soundly.
    """
    current: CoreSchema = schema
    while True:
        current_mapping = _mapping(current, "union branch")
        kind = current_mapping.get("type")
        if kind in {"definitions", "function-after"}:
            child = current_mapping.get("schema")
            if not isinstance(child, Mapping):
                raise TypeError(f"Unsupported {kind} wrapper in union branch")
            current = cast(CoreSchema, child)
        elif kind == "definition-ref":
            try:
                current = handler.resolve_ref_schema(current)
            except LookupError as error:
                raise TypeError(
                    "Unable to resolve generated union branch reference"
                ) from error
        elif kind in {"function-before", "function-wrap", "function-plain"}:
            raise TypeError(f"Unsupported model-level {kind} wrapper in union branch")
        else:
            break

    dataclass_schema = _mapping(current, "dataclass branch")
    if dataclass_schema.get("type") != "dataclass":
        raise TypeError(
            "Expected a Pydantic dataclass branch, got "
            f"{dataclass_schema.get('type')!r}"
        )
    cls = dataclass_schema.get("cls")
    if not isinstance(cls, type):
        raise TypeError("Unsupported dataclass CoreSchema without a class")

    config = _mapping(dataclass_schema.get("config", {}), "dataclass config")
    if config.get("extra_fields_behavior") != "forbid":
        raise TypeError(
            f"Dataclass {cls.__qualname__} must use extra='forbid' for safe dispatch"
        )

    arguments: object = dataclass_schema.get("schema")
    while True:
        args_schema = _mapping(arguments, "dataclass arguments")
        kind = args_schema.get("type")
        if kind == "definitions":
            arguments = args_schema.get("schema")
        elif kind == "function-after":
            arguments = args_schema.get("schema")
        elif kind in {"function-before", "function-wrap", "function-plain"}:
            raise TypeError(
                f"Unsupported model-level {kind} wrapper in dataclass "
                f"{cls.__qualname__}"
            )
        else:
            break

    if args_schema.get("type") != "dataclass-args":
        raise TypeError(
            f"Unsupported dataclass argument schema for {cls.__qualname__}: {kind!r}"
        )
    if args_schema.get("collect_init_only"):
        raise TypeError(
            f"Init-only dataclass fields are unsupported in {cls.__qualname__}"
        )

    raw_fields = args_schema.get("fields")
    if not isinstance(raw_fields, list):
        raise TypeError(f"Unsupported dataclass fields schema for {cls.__qualname__}")

    fields: list[_InputField] = []
    for raw_field in raw_fields:
        field = _mapping(raw_field, "dataclass field entry")
        if field.get("type") != "dataclass-field":
            raise TypeError(f"Unsupported field schema in {cls.__qualname__}")
        name = field.get("name")
        if not isinstance(name, str):
            raise TypeError(
                f"Unsupported dataclass field without a name in {cls.__qualname__}"
            )
        # CoreSchema may omit `init` for ordinary Field(...) declarations, so
        # only an explicit false value indicates that this is not an input field.
        if field.get("init") is False:
            raise TypeError(f"init=False fields are unsupported in {cls.__qualname__}")
        if field.get("init_only"):
            raise TypeError(
                f"Init-only dataclass fields are unsupported in {cls.__qualname__}"
            )
        fields.append(
            _InputField(
                name=name,
                accepted_keys=_accepted_keys(field, config),
                required=_is_required(field.get("schema")),
            )
        )
    return _Branch(schema=schema, cls=cls, fields=tuple(fields))


def _union_members(source_type: Any) -> tuple[Any, ...]:
    """Require a direct static union with at least two visible members."""
    origin = get_origin(source_type)
    members = get_args(source_type)
    if origin not in {Union, UnionType} or len(members) < 2:
        raise TypeError(
            "SelectByRequiredField supports only direct, statically visible unions"
        )
    return members


def _infer_identities(branches: tuple[_Branch, ...]) -> tuple[_Identity, ...]:
    """Infer one unique required input field for every union branch.

    Every accepted sibling key, including optional-field aliases, blocks a
    candidate identity. Ambiguous, missing, and non-unique identities fail
    during schema construction instead of falling back to trial validation.
    """
    identities: list[_Identity] = []
    for branch in branches:
        sibling_keys = frozenset(
            key
            for sibling in branches
            if sibling is not branch
            for field in sibling.fields
            for key in field.accepted_keys
        )
        candidates = [
            field
            for field in branch.fields
            if field.required and field.accepted_keys.isdisjoint(sibling_keys)
        ]
        if len(candidates) != 1:
            raise TypeError(
                f"Dataclass {branch.cls.__qualname__} has {len(candidates)} "
                "required input fields that uniquely identify its union branch; "
                "expected one"
            )
        field = candidates[0]
        # Prefer the Python name when it is accepted; otherwise the alias is the
        # stable tag used internally by Pydantic's tagged union.
        tag = (
            field.name
            if field.name in field.accepted_keys
            else next(iter(field.accepted_keys))
        )
        identities.append(_Identity(branch, tag, field.accepted_keys))

    tags = [identity.tag for identity in identities]
    if len(tags) != len(set(tags)):
        raise TypeError("Inferred union branch tags are not unique")
    return tuple(identities)


class SelectByRequiredField:
    """Select a static dataclass union using its generated required input keys.

    Mapping inputs select on key presence, not truthiness, so values such as
    ``{"wid": 0}`` reach the Workshop ID validator. Concrete dataclass instances
    select only when exactly one branch class matches. The original generated
    schemas remain intact for validation and serialization.

    Example:

        Selected = Annotated[Alpha | Beta, SelectByRequiredField()]

    The selector supports direct static unions of Pydantic dataclasses whose
    generated schema has one unambiguous required field per branch. Unsupported
    schemas fail at construction. Per-call ``TypeAdapter`` alias/name overrides
    are not visible to the selector; use schema-level configuration instead.
    """

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Build a callable tagged union from schemas generated for each member."""
        members = _union_members(source_type)
        branches = tuple(
            _inspect_branch(handler.generate_schema(member), handler)
            for member in members
        )
        identities = _infer_identities(branches)
        choices = {identity.tag: identity.branch.schema for identity in identities}
        if len(choices) != len(identities):
            raise TypeError("Inferred union branch tags are not unique")

        def select_tag(value: Any) -> str | None:
            """Choose one tag by present accepted keys or exact branch instance."""
            if isinstance(value, Mapping):
                matches = [
                    identity.tag
                    for identity in identities
                    if any(key in value for key in identity.accepted_keys)
                ]
            else:
                matches = [
                    identity.tag
                    for identity in identities
                    if isinstance(value, identity.branch.cls)
                ]
            return matches[0] if len(matches) == 1 else None

        key_description = ", ".join(
            " or ".join(sorted(identity.accepted_keys)) for identity in identities
        )
        return core_schema.tagged_union_schema(
            choices=choices,
            discriminator=select_tag,
            custom_error_type="variant_key_error",
            custom_error_message=(
                f"Expected exactly one variant key ({key_description})"
            ),
        )
