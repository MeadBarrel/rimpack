"""Tests for schema-derived dataclass-union selection and its support contract."""

from dataclasses import InitVar, field
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, TypeAlias

import pytest
from pydantic import (
    AliasChoices,
    AliasPath,
    ConfigDict,
    FailFast,
    Field,
    GetCoreSchemaHandler,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.dataclasses import dataclass as validated_dataclass
from pydantic_core import CoreSchema, core_schema

from rimpack.sdk._validation import EmptyableList, SelectByRequiredField
from rimpack.sdk.module import (
    AlsModRecord,
    AlsModReferenced,
    LocModRecord,
    LocModReferenced,
    ModRecords,
    Module,
    ModuleParseError,
    PidModRecord,
    PidModReferenced,
    ReferencedModRecord,
    ReferencedModRecords,
    WidModRecord,
    WidModReferenced,
    _PidRecordBase,
    _validated_identifier,
    parse_module_yaml,
)

ALL_REFERENCES_MODULE = """\
name: all_refs
mods:
  - pid: Main.Mod
    before:
      - pid: before.pid
      - wid: 12
      - loc: mods/before-local
      - als: before_alias
    after:
      - pid: after.pid
      - wid: 34
      - loc: mods/after-local
      - als: after_alias
  - wid: 000123
  - loc: mods/local
  - als: an_alias
"""


def _write_yaml(tmp_path: Path, source: str) -> Path:
    """Write one temporary module fixture and return its path."""
    path = tmp_path / "modules" / "fixture.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _error_details(error: ModuleParseError) -> list[dict[str, object]]:
    """Expose bounded structured Pydantic details retained by the parse error."""
    context = error.__context__
    assert isinstance(context, ValidationError)
    return context.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )


def _normalized_module(module: Module) -> tuple[object, ...]:
    """Return stable mod identities and constraints without depending on class names."""
    return (
        module.name,
        tuple(
            (
                record.reference,
                tuple(reference.reference for reference in record.before),
                tuple(reference.reference for reference in record.after),
            )
            for record in module.mods
        ),
    )


def _parse_failure(tmp_path: Path, source: str) -> ModuleParseError:
    """Parse invalid YAML and return its aggregate validation failure."""
    with pytest.raises(ModuleParseError) as captured:
        parse_module_yaml(_write_yaml(tmp_path, source))
    return captured.value


def test_emptyable_list_applies_to_future_collection_fields() -> None:
    """Reuse the opt-in collection type on a new field without parser changes."""

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class FutureSettings:
        """Model an unrelated future setting with an optional emptyable list."""

        arbitrary_rows: EmptyableList[StrictStr]

    empty = FutureSettings(arbitrary_rows="")
    assert empty.arbitrary_rows == ()
    assert FutureSettings(arbitrary_rows=[]).arbitrary_rows == ()
    assert FutureSettings(arbitrary_rows=("tuple",)).arbitrary_rows == ("tuple",)

    rows = ["one", "", "one"]
    parsed = FutureSettings(arbitrary_rows=rows)
    assert parsed.arbitrary_rows == ("one", "", "one")
    assert rows == ["one", "", "one"]

    for invalid in (None, False, 0, {}, " ", "null", "[]", "items"):
        with pytest.raises(ValidationError):
            FutureSettings(arbitrary_rows=invalid)

    with pytest.raises(ValidationError) as error:
        FutureSettings(arbitrary_rows=["valid", 12, "not validated after fail-fast"])
    assert [tuple(item["loc"]) for item in error.value.errors()] == [
        ("arbitrary_rows", 1)
    ]


def test_production_collections_dispatch_all_record_variants() -> None:
    """Dispatch each full and reference-only mapping to its concrete record."""
    mod_records = TypeAdapter(ModRecords).validate_python(
        [
            {"pid": "package.mod"},
            {"wid": "123"},
            {"loc": "mods/local"},
            {"als": "module_alias"},
        ]
    )
    reference_records = TypeAdapter(ReferencedModRecords).validate_python(
        [
            {"pid": "package.mod"},
            {"wid": "123"},
            {"loc": "mods/local"},
            {"als": "module_alias"},
        ]
    )

    assert [type(record) for record in mod_records] == [
        PidModRecord,
        WidModRecord,
        LocModRecord,
        AlsModRecord,
    ]
    assert [type(record) for record in reference_records] == [
        PidModReferenced,
        WidModReferenced,
        LocModReferenced,
        AlsModReferenced,
    ]


def test_all_variants_and_nested_constraints_preserve_order_and_values(
    tmp_path: Path,
) -> None:
    """Keep all reference kinds, normalized identities, and source order intact."""
    module = parse_module_yaml(_write_yaml(tmp_path, ALL_REFERENCES_MODULE))
    assert [type(record) for record in module.mods] == [
        PidModRecord,
        WidModRecord,
        LocModRecord,
        AlsModRecord,
    ]
    assert [type(reference) for reference in module.mods[0].before] == [
        PidModReferenced,
        WidModReferenced,
        LocModReferenced,
        AlsModReferenced,
    ]
    assert [type(reference) for reference in module.mods[0].after] == [
        PidModReferenced,
        WidModReferenced,
        LocModReferenced,
        AlsModReferenced,
    ]
    assert module.mods[0].pid == "Main.Mod"
    assert module.mods[0].reference.value == "main.mod"
    assert module.mods[1].wid == "000123"
    assert _normalized_module(module) == (
        "all_refs",
        (
            (
                module.mods[0].reference,
                (
                    module.mods[0].before[0].reference,
                    module.mods[0].before[1].reference,
                    module.mods[0].before[2].reference,
                    module.mods[0].before[3].reference,
                ),
                (
                    module.mods[0].after[0].reference,
                    module.mods[0].after[1].reference,
                    module.mods[0].after[2].reference,
                    module.mods[0].after[3].reference,
                ),
            ),
            (module.mods[1].reference, (), ()),
            (module.mods[2].reference, (), ()),
            (module.mods[3].reference, (), ()),
        ),
    )


def test_python_json_roundtrips_keep_concrete_variants_and_values(
    tmp_path: Path,
) -> None:
    """Preserve concrete records through Module validation and serialization."""
    parsed = parse_module_yaml(_write_yaml(tmp_path, ALL_REFERENCES_MODULE))
    adapter = TypeAdapter(Module)

    assert adapter.validate_python(parsed) == parsed
    assert adapter.validate_python(adapter.dump_python(parsed)) == parsed
    assert adapter.validate_json(adapter.dump_json(parsed)) == parsed
    assert [type(record) for record in adapter.validate_python(parsed).mods] == [
        PidModRecord,
        WidModRecord,
        LocModRecord,
        AlsModRecord,
    ]


def test_string_scalars_reach_the_selected_variant_validator(
    tmp_path: Path,
) -> None:
    """Treat scalar-looking YAML words as text before domain validation."""
    cases = (
        ("pid", '""', "value_error"),
        ("wid", "0", "value_error"),
        ("wid", "false", "value_error"),
        ("loc", '""', "value_error"),
        ("als", '""', "value_error"),
    )
    for key, value, expected_type in cases:
        error = _parse_failure(
            tmp_path,
            f"name: demo\nmods:\n  - {key}: {value}\n",
        )
        details = _error_details(error)
        assert error.location == "$"
        assert len(details) == 1
        assert details[0]["loc"] == ("mods", 0, key, key)
        assert details[0]["type"] == expected_type


def test_boolean_null_numeric_and_date_like_scalars_are_text(
    tmp_path: Path,
) -> None:
    """Preserve implicit-type-looking values as strings in domain records."""
    module = parse_module_yaml(
        _write_yaml(
            tmp_path,
            """name: lexical
mods:
  - pid: true
  - pid: false
  - pid: null
  - pid: 123
  - pid: 2025-99-99
  - loc: false
  - als: null
""",
        )
    )
    assert [record.pid for record in module.mods[:5]] == [
        "true",
        "false",
        "null",
        "123",
        "2025-99-99",
    ]
    assert isinstance(module.mods[5], LocModRecord)
    assert module.mods[5].loc.as_posix() == "false"
    assert isinstance(module.mods[6], AlsModRecord)
    assert module.mods[6].als == "null"


def test_missing_ambiguous_and_unknown_variant_keys_are_item_errors(
    tmp_path: Path,
) -> None:
    """Reject zero or multiple matching identities at the affected tuple item."""
    cases = (
        (
            "name: demo\nmods:\n  - before:\n      - pid: nested.mod\n",
            ("mods", 0),
        ),
        (
            "name: demo\nmods:\n  - pid: one.mod\n    wid: 10\n",
            ("mods", 0),
        ),
        (
            "name: demo\nmods:\n  - unknown: hidden\n",
            ("mods", 0),
        ),
        (
            "name: demo\nmods:\n  - PidModRecord: hidden\n",
            ("mods", 0),
        ),
        (
            "name: demo\nmods:\n  - pid: parent.mod\n    before:\n"
            "      - pid: one.mod\n        wid: 10\n",
            ("mods", 0, "pid", "before", 0),
        ),
    )
    for source, expected_location in cases:
        details = _error_details(_parse_failure(tmp_path, source))
        assert len(details) == 1
        assert details[0]["loc"] == expected_location
        assert details[0]["type"] == "variant_key_error"
        assert details[0]["msg"] == (
            "Expected exactly one variant key (pid, wid, loc, als)"
        )


def test_error_boundary_aggregates_relevant_details_and_suppresses_chaining(
    tmp_path: Path,
) -> None:
    """Render every relevant error at the aggregate root without exposing input."""
    secret = "private-reference-value"
    error = _parse_failure(
        tmp_path,
        """name: bad-name
mods:
  - pid: ""
    before:
      - wid: 0
    after: null
""",
    )
    details = _error_details(error)
    assert error.location == "$"
    assert error.line is None
    assert error.column is None
    assert [tuple(detail["loc"]) for detail in details] == [
        ("name",),
        ("mods", 0, "pid", "pid"),
        ("mods", 0, "pid", "before", 0, "wid", "wid"),
        ("mods", 0, "pid", "after"),
    ]
    assert error.message == "\n".join(
        f"{tuple(detail['loc'])!r}: {detail['msg']} [{detail['type']}]"
        for detail in details
    )
    assert "private-reference-value" not in error.message
    assert "errors.pydantic.dev" not in error.message
    assert isinstance(error.__context__, ValidationError)
    assert error.__cause__ is None
    assert error.__suppress_context__ is True

    unknown = _parse_failure(
        tmp_path,
        f"""name: demo
mods:
  - pid: parent.mod
    before:
      - hidden: {secret}
""",
    )
    assert secret not in unknown.message
    assert "errors.pydantic.dev" not in unknown.message


def test_tuple_failfast_stops_after_the_first_invalid_item(tmp_path: Path) -> None:
    """Retain FailFast on module and nested reference tuple collections."""
    error = _parse_failure(
        tmp_path,
        """name: okay
mods:
  - pid: ""
  - wid: 0
""",
    )
    details = _error_details(error)
    assert [tuple(detail["loc"]) for detail in details] == [("mods", 0, "pid", "pid")]


def test_schema_evolution_needs_no_selector_metadata_updates() -> None:
    """Infer renamed identities and an additional reference from generated schemas."""

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class RenamedPackage:
        package: StrictStr

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class RenamedWorkshop:
        workshop: StrictStr

    RenamedReference: TypeAlias = Annotated[
        RenamedPackage | RenamedWorkshop, SelectByRequiredField()
    ]
    renamed = TypeAdapter(RenamedReference).validate_python({"package": "some.mod"})
    assert isinstance(renamed, RenamedPackage)

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class ExternalReference:
        external: StrictStr

    ExtendedReference: TypeAlias = Annotated[
        ReferencedModRecord | ExternalReference, SelectByRequiredField()
    ]

    @validated_dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid"))
    class ExtendedOrdering:
        before: Annotated[tuple[ExtendedReference, ...], FailFast()] = ()
        after: Annotated[tuple[ExtendedReference, ...], FailFast()] = ()

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class ExtendedPidRecord(_PidRecordBase, ExtendedOrdering):
        """Full record using an extended inferred reference union."""

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class ExtendedModule:
        """Small root model for validating the extended ordering reference."""

        name: StrictStr
        mods: Annotated[tuple[ExtendedPidRecord, ...], FailFast()]

        @field_validator("name")
        @classmethod
        def _validate_name(cls, value: str) -> str:
            """Apply the production module-name rule to this integration test."""
            return _validated_identifier(value, "module name")

    extended = TypeAdapter(ExtendedModule).validate_python(
        {
            "name": "extended",
            "mods": [
                {
                    "pid": "parent.mod",
                    "before": [{"external": "remote_alias"}],
                }
            ],
        }
    )
    assert isinstance(extended.mods[0].before[0], ExternalReference)


def test_shared_required_and_keyword_only_identity_fields_are_supported() -> None:
    """Allow shared required data and keyword-only discriminating fields."""

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class SharedAlpha:
        shared: StrictStr
        alpha: StrictStr

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class SharedBeta:
        shared: StrictStr
        beta: StrictStr

    SharedUnion: TypeAlias = Annotated[
        SharedAlpha | SharedBeta, SelectByRequiredField()
    ]
    adapter = TypeAdapter(SharedUnion)
    assert isinstance(
        adapter.validate_python({"shared": "both", "alpha": "only-a"}),
        SharedAlpha,
    )
    with pytest.raises(ValidationError) as error:
        adapter.validate_python({"alpha": "missing-shared"})
    assert any(tuple(detail["loc"])[-1] == "shared" for detail in error.value.errors())

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class KeywordOnlyAlpha:
        alpha: StrictStr = field(kw_only=True)

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class KeywordOnlyBeta:
        beta: StrictStr = field(kw_only=True)

    KeywordOnlyUnion: TypeAlias = Annotated[
        KeywordOnlyAlpha | KeywordOnlyBeta, SelectByRequiredField()
    ]
    selected = TypeAdapter(KeywordOnlyUnion).validate_python({"alpha": "a"})
    assert isinstance(selected, KeywordOnlyAlpha)


def test_validation_aliases_generators_and_schema_configuration_are_respected() -> None:
    """Infer accepted keys from generated string aliases and dataclass config."""

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class PackageAlias:
        pid: str = Field(validation_alias="package")

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class WorkshopAlias:
        wid: Annotated[str, Field(validation_alias="workshop")]

    AliasUnion: TypeAlias = Annotated[
        PackageAlias | WorkshopAlias, SelectByRequiredField()
    ]
    alias_adapter = TypeAdapter(AliasUnion)
    assert isinstance(alias_adapter.validate_python({"package": "a.mod"}), PackageAlias)
    assert isinstance(alias_adapter.validate_python({"workshop": "12"}), WorkshopAlias)
    with pytest.raises(ValidationError):
        alias_adapter.validate_python({"pid": "a.mod"})

    config = ConfigDict(
        extra="forbid",
        alias_generator=lambda name: "yaml_" + name,
        populate_by_name=True,
    )

    @validated_dataclass(config=config)
    class GeneratedPackage:
        pid: str

    @validated_dataclass(config=config)
    class GeneratedWorkshop:
        wid: str

    GeneratedUnion: TypeAlias = Annotated[
        GeneratedPackage | GeneratedWorkshop, SelectByRequiredField()
    ]
    generated_adapter = TypeAdapter(GeneratedUnion)
    assert isinstance(
        generated_adapter.validate_python({"yaml_pid": "a.mod"}),
        GeneratedPackage,
    )
    assert isinstance(
        generated_adapter.validate_python({"pid": "a.mod"}), GeneratedPackage
    )

    name_config = ConfigDict(
        extra="forbid",
        alias_generator=lambda name: "yaml_" + name,
        validate_by_alias=False,
        validate_by_name=True,
    )

    @validated_dataclass(config=name_config)
    class NameOnlyAlpha:
        alpha: str

    @validated_dataclass(config=name_config)
    class NameOnlyBeta:
        beta: str

    NameOnlyUnion: TypeAlias = Annotated[
        NameOnlyAlpha | NameOnlyBeta, SelectByRequiredField()
    ]
    name_adapter = TypeAdapter(NameOnlyUnion)
    assert isinstance(name_adapter.validate_python({"alpha": "a"}), NameOnlyAlpha)
    with pytest.raises(ValidationError):
        name_adapter.validate_python({"yaml_alpha": "a"})


def test_field_defaults_and_optional_aliases_affect_identity_inference() -> None:
    """Distinguish field-level defaults while treating optional aliases as inputs."""

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class DefaultedAlpha:
        alpha: str
        note: str = Field(default="memo", validation_alias="note_yaml")

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class RequiredBeta:
        beta: str

    DefaultedUnion: TypeAlias = Annotated[
        DefaultedAlpha | RequiredBeta, SelectByRequiredField()
    ]
    parsed = TypeAdapter(DefaultedUnion).validate_python({"alpha": "value"})
    assert isinstance(parsed, DefaultedAlpha)
    assert parsed.note == "memo"

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class OptionalAlpha:
        alpha: str
        note: Annotated[str, Field(default="memo", validation_alias="beta")]

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class Beta:
        beta: str

    OptionalCollision: TypeAlias = Annotated[
        OptionalAlpha | Beta, SelectByRequiredField()
    ]
    with pytest.raises(TypeError, match="Beta has 0 required input fields"):
        TypeAdapter(OptionalCollision)


def test_alias_paths_and_choices_fail_during_schema_construction() -> None:
    """Reject compound aliases whose accepted input keys are not safely inferable."""

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class ChoiceAlpha:
        alpha: Annotated[str, Field(validation_alias=AliasChoices("one", "two"))]

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class ChoiceBeta:
        beta: str

    ChoiceUnion: TypeAlias = Annotated[
        ChoiceAlpha | ChoiceBeta, SelectByRequiredField()
    ]
    with pytest.raises(TypeError, match="only simple string aliases"):
        TypeAdapter(ChoiceUnion)

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class PathGamma:
        gamma: Annotated[str, Field(validation_alias=AliasPath("outer", "inner"))]

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class PathDelta:
        delta: str

    PathUnion: TypeAlias = Annotated[PathGamma | PathDelta, SelectByRequiredField()]
    with pytest.raises(TypeError, match="only simple string aliases"):
        TypeAdapter(PathUnion)


def test_alias_collisions_and_non_forbid_extras_fail_closed() -> None:
    """Reject shared aliases and branch schemas that may silently accept extras."""

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class SharedAliasAlpha:
        alpha: Annotated[str, Field(validation_alias="shared")]

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class SharedAliasBeta:
        beta: Annotated[str, Field(validation_alias="shared")]

    SharedAliasUnion: TypeAlias = Annotated[
        SharedAliasAlpha | SharedAliasBeta, SelectByRequiredField()
    ]
    with pytest.raises(TypeError, match="uniquely identify its union branch"):
        TypeAdapter(SharedAliasUnion)

    @validated_dataclass(config=ConfigDict(extra="ignore"))
    class IgnoreExtras:
        alpha: str

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class ForbidExtras:
        beta: str

    ExtraUnion: TypeAlias = Annotated[
        IgnoreExtras | ForbidExtras, SelectByRequiredField()
    ]
    with pytest.raises(TypeError, match="must use extra='forbid'"):
        TypeAdapter(ExtraUnion)


def test_resolved_forward_references_use_pydantic_schema() -> None:
    """Use Pydantic's resolved schema instead of Python type-hint reflection."""

    class Status(str, Enum):
        READY = "ready"

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class EnumAlpha:
        alpha: "Status"

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class PlainBeta:
        beta: str

    ForwardUnion: TypeAlias = Annotated[EnumAlpha | PlainBeta, SelectByRequiredField()]
    selected = TypeAdapter(ForwardUnion).validate_python({"alpha": "ready"})
    assert isinstance(selected, EnumAlpha)
    assert selected.alpha is Status.READY


def test_after_and_field_validators_remain_in_the_original_branch_schema() -> None:
    """Retain input-neutral model-after and ordinary field-before validators."""

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class AfterAlpha:
        alpha: str
        checked: bool = False

        @model_validator(mode="after")
        def mark_checked(self) -> AfterAlpha:
            self.checked = True
            return self

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class PlainBeta:
        beta: str

    AfterUnion: TypeAlias = Annotated[AfterAlpha | PlainBeta, SelectByRequiredField()]
    after = TypeAdapter(AfterUnion).validate_python({"alpha": "value"})
    assert isinstance(after, AfterAlpha)
    assert after.checked

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class BeforeAlpha:
        alpha: str

        @field_validator("alpha", mode="before")
        @classmethod
        def normalize(cls, value: object) -> object:
            return str(value).strip()

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class AnotherBeta:
        beta: str

    BeforeUnion: TypeAlias = Annotated[
        BeforeAlpha | AnotherBeta, SelectByRequiredField()
    ]
    before = TypeAdapter(BeforeUnion).validate_python({"alpha": "  value  "})
    assert isinstance(before, BeforeAlpha)
    assert before.alpha == "value"


def test_input_transforming_model_validators_are_rejected_at_build_time() -> None:
    """Fail schema creation when model wrappers can change accepted mapping keys."""

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class BeforeModel:
        alpha: str

        @model_validator(mode="before")
        @classmethod
        def accept_legacy(cls, value: object) -> object:
            if isinstance(value, dict) and "legacy_alpha" in value:
                return {"alpha": value["legacy_alpha"]}
            return value

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class PlainBeta:
        beta: str

    BeforeUnion: TypeAlias = Annotated[BeforeModel | PlainBeta, SelectByRequiredField()]
    with pytest.raises(TypeError, match="model-level function-before"):
        TypeAdapter(BeforeUnion)

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class WrapModel:
        gamma: str

        @model_validator(mode="wrap")
        @classmethod
        def keep_input(cls, value: object, handler: Any) -> object:
            return handler(value)

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class PlainDelta:
        delta: str

    WrapUnion: TypeAlias = Annotated[WrapModel | PlainDelta, SelectByRequiredField()]
    with pytest.raises(TypeError, match="model-level function-wrap"):
        TypeAdapter(WrapUnion)


def test_function_plain_schemas_are_rejected_at_build_time() -> None:
    """Reject a custom plain schema wrapper even without a validator decorator."""

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class Alpha:
        alpha: str

    @validated_dataclass(config=ConfigDict(extra="forbid"))
    class Beta:
        beta: str

    class PlainSchema:
        """Expose a function-plain shape using Pydantic's public schema API."""

        def __get_pydantic_core_schema__(
            self, source_type: Any, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            """Return a schema shape the selector deliberately does not support."""
            return core_schema.no_info_plain_validator_function(lambda value: value)

    PlainAlpha: TypeAlias = Annotated[Alpha, PlainSchema()]
    PlainUnion: TypeAlias = Annotated[PlainAlpha | Beta, SelectByRequiredField()]
    with pytest.raises(TypeError, match="model-level function-plain"):
        TypeAdapter(PlainUnion)


def test_init_only_explicit_non_init_and_ambiguous_schemas_fail_closed() -> None:
    """Reject unsupported dataclass inputs and identities during schema building."""

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class HasTwoUniqueFields:
        alpha: str
        secondary: str

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class HasOneUniqueField:
        beta: str

    TwoFields: TypeAlias = Annotated[
        HasTwoUniqueFields | HasOneUniqueField, SelectByRequiredField()
    ]
    with pytest.raises(TypeError, match="2 required input fields"):
        TypeAdapter(TwoFields)

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class InitVarAlpha:
        token: str
        extra: InitVar[str]

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class RequiredAlpha:
        alpha: str

    InitVarUnion: TypeAlias = Annotated[
        InitVarAlpha | RequiredAlpha, SelectByRequiredField()
    ]
    with pytest.raises(TypeError, match="Init-only dataclass fields are unsupported"):
        TypeAdapter(InitVarUnion)

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class NotInput:
        identity: str = field(init=False, default="not-an-input")

    @validated_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
    class OtherInput:
        other: str

    NotInputUnion: TypeAlias = Annotated[NotInput | OtherInput, SelectByRequiredField()]
    with pytest.raises(TypeError, match="init=False fields are unsupported"):
        TypeAdapter(NotInputUnion)


def test_pep695_alias_and_ambiguous_multiple_inheritance_fail_clearly() -> None:
    """Reject hidden type-alias unions and ambiguous concrete instances."""
    type PEP695Reference = PidModReferenced | WidModReferenced
    hidden_alias: TypeAlias = Annotated[PEP695Reference, SelectByRequiredField()]
    with pytest.raises(TypeError, match="direct, statically visible unions"):
        TypeAdapter(hidden_alias)

    class AmbiguousReference(PidModReferenced, WidModReferenced):
        """A concrete object matching two distinct member classes."""

    value = object.__new__(AmbiguousReference)
    object.__setattr__(value, "pid", "parent.mod")
    object.__setattr__(value, "wid", "123")
    adapter = TypeAdapter(Annotated[ReferencedModRecord, SelectByRequiredField()])
    with pytest.raises(ValidationError) as error:
        adapter.validate_python(value)
    details = error.value.errors(include_input=False, include_url=False)
    assert len(details) == 1
    assert details[0]["type"] == "variant_key_error"
    assert details[0]["loc"] == ()


def test_per_call_alias_name_overrides_are_outside_the_contract() -> None:
    """Document that a value-only discriminator cannot observe TypeAdapter flags."""
    config = ConfigDict(
        extra="forbid",
        alias_generator=lambda name: "yaml_" + name,
    )

    @validated_dataclass(config=config)
    class Alpha:
        alpha: str

    @validated_dataclass(config=config)
    class Beta:
        beta: str

    assert (
        TypeAdapter(Alpha).validate_python({"alpha": "value"}, by_name=True).alpha
        == "value"
    )
    Union: TypeAlias = Annotated[Alpha | Beta, SelectByRequiredField()]
    with pytest.raises(ValidationError) as error:
        TypeAdapter(Union).validate_python({"alpha": "value"}, by_name=True)
    assert error.value.errors()[0]["type"] == "variant_key_error"
