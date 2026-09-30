"""Tests for the complete module-file data model and YAML parser."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from rimpack.sdk.module import (
    LocModRecord,
    LocModReferenced,
    LocReference,
    Module,
    ModuleParseError,
    PidModRecord,
    PidModReferenced,
    PidReference,
    WidModRecord,
    WidModReferenced,
    WidReference,
    parse_module_yaml,
)


def write_module(tmp_path: Path, contents: str) -> Path:
    """Write module YAML below a nested directory and return its file path."""
    module_path = tmp_path / "modules" / "example.yml"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(contents, encoding="utf-8")
    return module_path


def parse_yaml(tmp_path: Path, contents: str) -> Module:
    """Parse the supplied YAML using a temporary module file."""
    return parse_module_yaml(write_module(tmp_path, contents))


def validation_details(error: ModuleParseError) -> list[dict[str, object]]:
    """Return structured Pydantic details retained by an aggregate parse error."""
    context = error.__context__
    assert isinstance(context, ValidationError)
    return context.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )


def test_parses_specification_examples(tmp_path: Path) -> None:
    """Parse the simple package-ID and Workshop-ID examples from the spec."""
    module = parse_yaml(
        tmp_path,
        """name: ludeon
mods:
  - pid: ludeon.rimworld
  - pid: ludeon.rimworld.royalty
""",
    )
    assert module.name == "ludeon"
    assert module.mods == (
        PidModRecord(pid="ludeon.rimworld"),
        PidModRecord(pid="ludeon.rimworld.royalty"),
    )

    frameworks = parse_yaml(
        tmp_path,
        """name: frameworks
mods:
  - wid: 2009463077
""",
    )
    assert frameworks.mods == (WidModRecord(wid="2009463077"),)


def test_parses_all_reference_variants_and_unresolved_local_paths(
    tmp_path: Path,
) -> None:
    """Parse each supported full-entry variant without resolving local targets."""
    module = parse_yaml(
        tmp_path,
        """name: all_refs
mods:
  - pid: Some.Author.Mod
  - wid: "000123"
  - loc: mods/not-installed
""",
    )
    assert isinstance(module.mods[0], PidModRecord)
    assert isinstance(module.mods[1], WidModRecord)
    assert isinstance(module.mods[2], LocModRecord)
    assert module.mods[2].loc == Path("mods/not-installed")
    assert module.mods[0].pid == "Some.Author.Mod"
    assert module.mods[1].wid == "000123"
    assert module.mods[1].reference == WidReference("000123")
    assert module.mods[1].reference.value == "123"


def assert_parses_each_reference_kind_in_before_and_after(
    tmp_path: Path,
    field: str,
    yaml_value: str,
    expected_type: type[object],
) -> None:
    """Allow each reference-only YAML shape in either constraint list."""
    module = parse_yaml(
        tmp_path,
        f"""name: constraints
mods:
  - pid: current.mod
    {field}:
      - {yaml_value}
""",
    )
    record = module.mods[0]
    references = getattr(record, field)
    assert len(references) == 1
    assert isinstance(references[0], expected_type)
    assert not hasattr(references[0], "before")
    assert not hasattr(references[0], "after")


@pytest.mark.parametrize(
    ("field", "yaml_value", "expected_type"),
    [
        (field, value, cls)
        for field in ("before", "after")
        for value, cls in (
            ("pid: other.mod", PidModReferenced),
            ("wid: 12345", WidModReferenced),
            ("loc: mods/other", LocModReferenced),
        )
    ],
)
def test_constraint_reference_matrix(
    tmp_path: Path,
    field: str,
    yaml_value: str,
    expected_type: type[object],
) -> None:
    """Cover all reference kinds in both before and after lists."""
    assert_parses_each_reference_kind_in_before_and_after(
        tmp_path, field, yaml_value, expected_type
    )


def test_preserves_mod_and_constraint_order_and_repetitions(tmp_path: Path) -> None:
    """Keep repeated entries and constraints in exactly their YAML order."""
    module = parse_yaml(
        tmp_path,
        """name: ordered
mods:
  - pid: first.mod
    before:
      - wid: 20
      - pid: target.mod
      - wid: 20
  - pid: second.mod
  - pid: first.mod
""",
    )
    assert [
        record.pid for record in module.mods if isinstance(record, PidModRecord)
    ] == [
        "first.mod",
        "second.mod",
        "first.mod",
    ]
    assert module.mods[0].before == (
        WidModReferenced(wid="20"),
        PidModReferenced(pid="target.mod"),
        WidModReferenced(wid="20"),
    )


def test_empty_mod_and_constraint_lists_are_valid(tmp_path: Path) -> None:
    """Accept omitted and blank collections as immutable empty tuples."""
    module = parse_yaml(
        tmp_path,
        """name: empty
mods:
  - pid: empty.constraints
    before:
    after:
""",
    )
    assert parse_yaml(tmp_path, "name: no_mods\n").mods == ()
    assert isinstance(module.mods[0], PidModRecord)
    assert module.mods[0].before == ()
    assert module.mods[0].after == ()


@pytest.mark.parametrize("empty_value", ["", "''", '""'])
@pytest.mark.parametrize("field", ["mods", "before", "after"])
def test_blank_collection_values_become_empty_tuples(
    tmp_path: Path, field: str, empty_value: str
) -> None:
    """Normalize only empty scalar spellings at each emptyable list field."""
    if field == "mods":
        source = f"name: blank_{field}\nmods: {empty_value} # intentionally empty\n"
        assert parse_yaml(tmp_path, source).mods == ()
    else:
        source = (
            f"name: blank_{field}\nmods:\n  - pid: parent.mod\n"
            f"    {field}: {empty_value} # intentionally empty\n"
        )
        record = parse_yaml(tmp_path, source).mods[0]
        assert getattr(record, field) == ()


def test_module_collections_default_and_normalize_only_empty_strings() -> None:
    """Apply the reusable emptyable-list contract to direct Module construction."""
    assert Module(name="implicit_empty").mods == ()
    assert Module(name="explicit_empty", mods="").mods == ()  # type: ignore[arg-type]
    record = PidModRecord(pid="blank_constraints", before="")  # type: ignore[arg-type]
    assert record.before == ()
    with pytest.raises(ValidationError):
        Module(name="not_none", mods=None)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        PidModRecord(pid="not_none", before=None)  # type: ignore[arg-type]


def test_reference_values_preserve_source_and_canonicalize_pid_identity() -> None:
    """Retain source spelling while making derived PID identity case-insensitive."""
    original = PidModReferenced(pid="Some.Author.Mod")
    lower = PidModReferenced(pid="some.author.mod")
    direct = PidReference("SOME.AUTHOR.MOD")
    assert original.pid == "Some.Author.Mod"
    assert original.reference == lower.reference == direct
    assert original.reference.value == "some.author.mod"
    assert hash(original.reference) == hash(lower.reference)

    unchecked = PidReference("Not A Valid Package ID")
    assert unchecked.value == "not a valid package id"


@pytest.mark.parametrize("value", ["", '"has space"', '"M\\u00fcd"'])
def test_rejects_non_ascii_or_whitespace_package_ids(
    tmp_path: Path, value: str
) -> None:
    """Apply the approved initial ASCII package-ID support policy."""
    with pytest.raises(ModuleParseError):
        parse_yaml(tmp_path, f"name: pid\nmods:\n  - pid: {value}\n")


@pytest.mark.parametrize("location", ["mods", "before", "after"])
@pytest.mark.parametrize(
    "identity", [None, "pid: supported.mod", "wid: 123", "loc: mods/local"]
)
def test_rejects_alias_references(
    tmp_path: Path, location: str, identity: str | None
) -> None:
    """Reject aliases alone or beside a supported identity at every YAML location."""
    fields = ["als: valid_alias"]
    if identity is not None:
        fields.insert(0, identity)
    if location == "mods":
        entry = "\n    ".join(fields)
        source = f"name: no_aliases\nmods:\n  - {entry}\n"
        expected_location = ("mods", 0)
    else:
        reference = "\n        ".join(fields)
        source = (
            "name: no_aliases\nmods:\n  - pid: parent.mod\n"
            f"    {location}:\n      - {reference}\n"
        )
        expected_location = ("mods", 0, "pid", location, 0)
    expected_type = "variant_key_error"
    if identity is not None:
        expected_location += (identity.split(":")[0], "als")
        expected_type = "unexpected_keyword_argument"

    with pytest.raises(ModuleParseError) as error:
        parse_yaml(tmp_path, source)

    assert error.value.location == "$"
    details = validation_details(error.value)
    assert len(details) == 1
    assert details[0]["loc"] == expected_location
    assert details[0]["type"] == expected_type


def test_full_entries_and_reference_records_are_siblings() -> None:
    """Ensure full module entries cannot type-check as reference-only records."""
    assert not issubclass(PidModRecord, PidModReferenced)
    assert not issubclass(WidModRecord, WidModReferenced)
    assert not issubclass(LocModRecord, LocModReferenced)
    assert PidModRecord("a.mod", before=(PidModReferenced("b.mod"),))


def test_records_are_frozen() -> None:
    """Keep validated records and modules immutable after construction."""
    record = PidModRecord(pid="frozen.mod")
    with pytest.raises(FrozenInstanceError):
        record.pid = "changed.mod"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        Module(name="frozen", mods=(record,)).name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("yaml_value", "expected"),
    [
        ("123", "123"),
        ("00123", "00123"),
        ('"00123"', "00123"),
        ("18446744073709551615", "18446744073709551615"),
        ('"18446744073709551615"', "18446744073709551615"),
    ],
)
def test_accepts_positive_workshop_ids_and_preserves_digit_spelling(
    tmp_path: Path, yaml_value: str, expected: str
) -> None:
    """Treat bare and quoted decimal scalars as text, preserving leading zeros."""
    module = parse_yaml(tmp_path, f"name: workshop\nmods:\n  - wid: {yaml_value}\n")
    assert module.mods == (WidModRecord(wid=expected),)


def test_workshop_references_match_across_leading_zero_spellings(
    tmp_path: Path,
) -> None:
    """Match full entries and ordering targets by Workshop ID, not spelling."""
    module = parse_yaml(
        tmp_path,
        """name: workshop_identity
mods:
  - wid: 000123
  - pid: earlier.mod
    before:
      - wid: 123
  - pid: later.mod
    after:
      - wid: "000000123"
""",
    )
    workshop, earlier, later = module.mods
    assert isinstance(workshop, WidModRecord)
    assert isinstance(earlier, PidModRecord)
    assert isinstance(later, PidModRecord)
    assert workshop.wid == "000123"
    assert earlier.before[0].wid == "123"
    assert later.after[0].wid == "000000123"
    identities = (
        workshop.reference,
        earlier.before[0].reference,
        later.after[0].reference,
        WidReference("123"),
    )
    assert all(identity.value == "123" for identity in identities)
    assert len(set(identities)) == 1


def test_workshop_identity_handles_heavily_zero_padded_ids(tmp_path: Path) -> None:
    """Canonicalize valid padded IDs without converting huge strings to integers."""
    padded = "0" * 5000 + "123"
    module = parse_yaml(tmp_path, f"name: padded\nmods:\n  - wid: {padded}\n")
    assert isinstance(module.mods[0], WidModRecord)
    assert module.mods[0].wid == padded
    assert module.mods[0].reference == WidReference("123")
    assert module.mods[0].reference.value == "123"


def test_rejects_explicit_yaml_tags(tmp_path: Path) -> None:
    """Reject explicit scalar tags as unsupported StrictYAML syntax."""
    with pytest.raises(ModuleParseError, match="tag") as error:
        parse_yaml(tmp_path, "name: workshop\nmods:\n  - wid: !!int 00123\n")
    assert error.value.line == 3
    assert error.value.column is not None


@pytest.mark.parametrize("quoted", [False, True])
def test_rejects_oversized_workshop_ids_as_module_parse_errors(
    tmp_path: Path, quoted: bool
) -> None:
    """Reject enormous decimal IDs without leaking integer-conversion errors."""
    digits = "9" * 5000
    yaml_value = f'"{digits}"' if quoted else digits
    with pytest.raises(ModuleParseError) as error:
        parse_yaml(tmp_path, f"name: workshop\nmods:\n  - wid: {yaml_value}\n")
    assert error.value.location == "$"
    assert error.value.line is None
    assert error.value.column is None
    details = validation_details(error.value)
    assert len(details) == 1
    assert details[0]["loc"] == ("mods", 0, "wid", "wid")
    assert details[0]["type"] == "value_error"
    assert "must not exceed" in details[0]["msg"]


def test_yaml_scalar_words_remain_strings(tmp_path: Path) -> None:
    """Keep boolean-, null-, and YAML 1.1-looking words as domain strings."""
    module = parse_yaml(
        tmp_path,
        """name: on
mods:
  - pid: yes
  - pid: true
  - pid: false
  - pid: null
  - pid: no
  - loc: off
""",
    )
    assert module.name == "on"
    assert module.mods == (
        PidModRecord(pid="yes"),
        PidModRecord(pid="true"),
        PidModRecord(pid="false"),
        PidModRecord(pid="null"),
        PidModRecord(pid="no"),
        LocModRecord(loc=Path("off")),
    )


@pytest.mark.parametrize(
    "value",
    [
        "0",
        '"000"',
        "-1",
        "1.5",
        "+123",
        "1_000",
        '"1x"',
        "true",
        "18446744073709551616",
        '"18446744073709551616"',
    ],
)
def test_rejects_invalid_workshop_ids(tmp_path: Path, value: str) -> None:
    """Reject nonpositive, nondecimal, boolean, and out-of-range Workshop IDs."""
    with pytest.raises(ModuleParseError, match="Workshop ID"):
        parse_yaml(tmp_path, f"name: workshop\nmods:\n  - wid: {value}\n")


@pytest.mark.parametrize("value", ["", '"   "', '"mods/\\0bad"'])
def test_rejects_invalid_local_path_values(tmp_path: Path, value: str) -> None:
    """Reject blank and NUL-containing local path strings."""
    with pytest.raises(ModuleParseError):
        parse_yaml(tmp_path, f"name: local\nmods:\n  - loc: {value}\n")


def test_local_paths_are_unresolved_and_need_not_exist(tmp_path: Path) -> None:
    """Keep relative and absolute paths as written without probing their targets."""
    absolute = tmp_path / "does-not-exist"
    module = parse_yaml(
        tmp_path,
        f"""name: paths
mods:
  - loc: relative/not-installed
  - loc: '{absolute.as_posix()}'
""",
    )
    assert module.mods[0].reference == LocReference(Path("relative/not-installed"))
    assert module.mods[1].reference == LocReference(absolute)
    assert not absolute.exists()

    spaced = parse_yaml(
        tmp_path,
        'name: spaces\nmods:\n  - loc: "mods/my mod"\n',
    )
    assert isinstance(spaced.mods[0], LocModRecord)
    assert spaced.mods[0].loc == Path("mods/my mod")
    numeric = parse_yaml(tmp_path, "name: numeric_path\nmods:\n  - loc: 123\n")
    assert numeric.mods[0].loc == Path("123")


def test_comments_multiline_paths_and_windows_backslashes_are_plain_text(
    tmp_path: Path,
) -> None:
    """Ignore comments while retaining multiline and Windows path text."""
    module = parse_yaml(
        tmp_path,
        r"""# module comment
name: paths
mods:
  # first mod comment
  - pid: first.mod # inline note
  - loc: >-
      D:\RimWorld\Mods\Local
      Folder
""",
    )
    assert module.mods[0] == PidModRecord(pid="first.mod")
    assert isinstance(module.mods[1], LocModRecord)
    assert str(module.mods[1].loc) == r"D:\RimWorld\Mods\Local Folder"


@pytest.mark.parametrize(
    ("yaml_text", "detail_location", "detail_type"),
    [
        ("mods:\n", ("name",), "missing"),
        ("name: invalid-name\nmods:\n", ("name",), "value_error"),
        ("name: demo\nmods: not_a_list\n", ("mods",), "tuple_type"),
        (
            "name: demo\nmods:\n  - before:\n",
            ("mods", 0),
            "variant_key_error",
        ),
        (
            "name: demo\nmods:\n  - pid: a\n    wid: 123\n",
            ("mods", 0),
            "variant_key_error",
        ),
    ],
)
def test_rejects_incomplete_or_invalid_module_shapes(
    tmp_path: Path,
    yaml_text: str,
    detail_location: tuple[str | int, ...],
    detail_type: str,
) -> None:
    """Require valid module fields and exactly one mod-reference identity."""
    with pytest.raises(ModuleParseError) as error:
        parse_yaml(tmp_path, yaml_text)
    assert error.value.location == "$"
    details = validation_details(error.value)
    assert len(details) == 1
    assert details[0]["loc"] == detail_location
    assert details[0]["type"] == detail_type


@pytest.mark.parametrize("constraint", ["before", "after"])
def test_reports_missing_nested_reference_at_constraint_location(
    tmp_path: Path, constraint: str
) -> None:
    """Point to a malformed nested reference instead of another union branch."""
    with pytest.raises(ModuleParseError) as error:
        parse_yaml(
            tmp_path,
            f"""name: demo
mods:
  - pid: valid.mod
    {constraint}:
      - unknown: hidden
""",
        )
    assert error.value.location == "$"
    details = validation_details(error.value)
    assert len(details) == 1
    assert details[0]["loc"] == ("mods", 0, "pid", constraint, 0)
    assert details[0]["type"] == "variant_key_error"


@pytest.mark.parametrize(
    "source",
    [
        "name: flow_sequence\nmods: []\n",
        "name: flow_mapping\nmods:\n  - {pid: a.mod}\n",
        "name: anchored\nmods:\n  - &entry\n    pid: a.mod\n",
        "name: aliased\nmods:\n  - *entry\n",
    ],
)
def test_rejects_flow_tags_anchors_and_aliases(tmp_path: Path, source: str) -> None:
    """Reject YAML features outside the StrictYAML module-file subset."""
    with pytest.raises(ModuleParseError) as error:
        parse_yaml(tmp_path, source)
    assert error.value.line is not None
    assert error.value.column is not None


@pytest.mark.parametrize("value", ["null", "'{}'", '"not-a-list"'])
def test_rejects_non_list_constraint_values(tmp_path: Path, value: str) -> None:
    """Reject nulls, mappings, and scalars where constraint sequences are expected."""
    with pytest.raises(ModuleParseError):
        parse_yaml(
            tmp_path,
            f"name: constraints\nmods:\n  - pid: a.mod\n    before: {value}\n",
        )


def test_rejects_unknown_fields_and_nested_constraint_fields(tmp_path: Path) -> None:
    """Reject unsupported root, entry, and reference-only mapping fields."""
    invalid_modules = (
        "name: demo\nmods:\nextra: true\n",
        "name: demo\nmods:\n  - pid: a.mod\n    extra: true\n",
        (
            "name: demo\nmods:\n  - pid: a.mod\n    before:\n"
            "      - pid: b.mod\n        after:\n          - pid: c.mod\n"
        ),
    )
    for source in invalid_modules:
        with pytest.raises(ModuleParseError):
            parse_yaml(tmp_path, source)

    with pytest.raises(ModuleParseError) as error:
        parse_yaml(
            tmp_path,
            """name: demo
mods:
  - pid: valid.mod
    before:
      - pid: other.mod
        after:
          - pid: nested.mod
""",
        )
    assert error.value.location == "$"
    details = validation_details(error.value)
    assert len(details) == 1
    assert details[0]["loc"] == (
        "mods",
        0,
        "pid",
        "before",
        0,
        "pid",
        "after",
    )
    assert details[0]["msg"] == "Unexpected keyword argument"
    assert details[0]["type"] == "unexpected_keyword_argument"


def test_reports_first_invalid_mod_with_logical_location(tmp_path: Path) -> None:
    """Stop at the first invalid entry and identify its zero-based list index."""
    with pytest.raises(ModuleParseError) as error:
        parse_yaml(
            tmp_path,
            """name: first_error
mods:
  - pid: valid.mod
  - pid: ""
  - pid: also.invalid
""",
        )
    assert error.value.location == "$"
    details = validation_details(error.value)
    assert len(details) == 1
    assert details[0]["loc"] == ("mods", 1, "pid", "pid")
    assert details[0]["type"] == "value_error"
    assert "package ID must be nonempty" in details[0]["msg"]


@pytest.mark.parametrize(
    "source",
    [
        "name: demo\nname: duplicate\nmods:\n",
        "name: demo\nmods:\n  - pid: a.mod\n    pid: b.mod\n",
        (
            "name: demo\nmods:\n  - pid: a.mod\n    before:\n"
            "      - wid: 1\n        wid: 2\n"
        ),
    ],
)
def test_duplicate_yaml_keys_are_rejected_with_source_marks(
    tmp_path: Path, source: str
) -> None:
    """Reject duplicate keys before StrictYAML can overwrite them."""
    with pytest.raises(ModuleParseError) as error:
        parse_yaml(tmp_path, source)
    assert error.value.line is not None
    assert error.value.column is not None
    assert "duplicate key" in str(error.value).lower()


def test_rejects_multiple_documents(tmp_path: Path) -> None:
    """Reject YAML streams containing more than one module document."""
    source = "name: one\nmods:\n---\nname: two\nmods:\n"
    with pytest.raises(ModuleParseError):
        parse_yaml(tmp_path, source)


def test_accepts_utf8_bom_and_reports_decode_errors(tmp_path: Path) -> None:
    """Accept an optional UTF-8 BOM and translate invalid bytes into parser errors."""
    path = write_module(tmp_path, "name: bom\nmods:\n")
    path.write_bytes(b"\xef\xbb\xbfname: bom\nmods:\n")
    assert parse_module_yaml(path).name == "bom"

    path.write_bytes(b"name: \xff\nmods:\n")
    with pytest.raises(ModuleParseError, match="UTF-8"):
        parse_module_yaml(path)


def test_yaml_syntax_errors_include_source_line_and_column(tmp_path: Path) -> None:
    """Expose one-based source positions for syntax errors reported by StrictYAML."""
    with pytest.raises(ModuleParseError) as error:
        parse_yaml(tmp_path, "name: demo\nmods: [\n")
    assert error.value.line is not None
    assert error.value.column is not None


@pytest.mark.parametrize("character", ["\x00", "\x01", "\x1f"])
def test_invalid_yaml_control_characters_are_parse_errors(
    tmp_path: Path, character: str
) -> None:
    """Convert StrictYAML reader failures for literal control characters."""
    path = write_module(tmp_path, f"name: demo\nmods:\n  - pid: a{character}b\n")
    with pytest.raises(ModuleParseError) as error:
        parse_module_yaml(path)
    assert error.value.path == path
    assert error.value.location == "$"
    assert error.value.message.startswith("unacceptable character")


def test_empty_and_comment_only_documents_are_rejected(tmp_path: Path) -> None:
    """Reject documents with no YAML content using a stable parser error."""
    for source in (
        "",
        "  " + "\n" + "\t" + "\n",
        "# only a comment" + "\n\n  # still empty\n",
    ):
        with pytest.raises(ModuleParseError, match="document must not be empty"):
            parse_yaml(tmp_path, source)


def test_nonmapping_yaml_root_is_rejected(tmp_path: Path) -> None:
    """Require one mapping at the document root before domain validation."""
    with pytest.raises(ModuleParseError, match="expected a YAML mapping"):
        parse_yaml(tmp_path, "plain scalar root\n")


def test_deeply_nested_unknown_values_fail_with_a_controlled_error(
    tmp_path: Path,
) -> None:
    """Bound deeply nested input and ensure failures remain parser errors."""
    depth = 256
    lines = ["name: deep", "mods:", "extra:"]
    lines.extend(" " * (2 * (level + 1)) + "nested:" for level in range(depth))
    lines.append(" " * (2 * (depth + 1)) + "value")

    with pytest.raises(ModuleParseError) as error:
        parse_yaml(tmp_path, "\n".join(lines) + "\n")
    assert error.value.path == tmp_path / "modules" / "example.yml"
    assert error.value.location == "$"


def test_filesystem_errors_remain_os_errors(tmp_path: Path) -> None:
    """Leave ordinary missing-file errors as OSError subclasses."""
    with pytest.raises(FileNotFoundError):
        parse_module_yaml(tmp_path / "missing.yml")
