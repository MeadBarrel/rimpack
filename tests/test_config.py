"""Tests for immutable global settings, strict YAML, and file selection."""

import os
import socket
import stat
import subprocess
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from rimpack.sdk import config
from rimpack.sdk.config import (
    ConfigLoadResult,
    ConfigParseError,
    Settings,
    load_config,
    parse_config_yaml,
    select_config_path,
)
from rimpack.sdk.diagnostics import (
    UnknownConfigFieldDiagnostic,
    render_diagnostics,
)

_PATH_FIELDS = ("rimworld_path", "workshop_path", "data_path", "mods_path")


def write_config(tmp_path: Path, contents: str) -> Path:
    """Write UTF-8 settings in a nested directory and return their file path."""
    path = tmp_path / "profile" / "settings.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def parse_yaml(tmp_path: Path, contents: str) -> ConfigLoadResult:
    """Parse supplied YAML from a temporary settings file."""
    return parse_config_yaml(write_config(tmp_path, contents))


def set_home(monkeypatch, home: Path) -> None:
    """Isolate both Path.home and host-platform leading-tilde expansion."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


def make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    """Create a symlink, skipping hosts without the required OS permission."""
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlinks are unavailable: {error}")


@pytest.mark.skipif(os.name != "nt", reason="Windows drive-relative syntax")
@pytest.mark.parametrize("value", ["C:game", "c:game", "C:", Path("C:game")])
@pytest.mark.parametrize("field", (*_PATH_FIELDS, "extra_mod_paths"))
def test_windows_drive_relative_settings_are_rejected(field: str, value) -> None:
    """Reject per-drive working-directory dependence in all settings paths."""
    supplied = [value] if field == "extra_mod_paths" else value
    with pytest.raises(ValidationError, match="drive-relative paths"):
        Settings(**{field: supplied})


@pytest.mark.skipif(os.name != "nt", reason="Windows drive-relative syntax")
@pytest.mark.parametrize("field", (*_PATH_FIELDS, "extra_mod_paths"))
def test_windows_drive_relative_yaml_paths_are_rejected(
    tmp_path: Path, field: str
) -> None:
    """Translate rejected YAML path values into source-aware parse errors."""
    source = (
        "extra_mod_paths:\n  - C:game\n"
        if field == "extra_mod_paths"
        else f"{field}: C:game\n"
    )
    with pytest.raises(ConfigParseError, match="drive-relative paths"):
        parse_yaml(tmp_path, source)


@pytest.mark.skipif(os.name != "nt", reason="Windows drive-relative syntax")
@pytest.mark.parametrize(
    "value", ["C:settings.yml", "c:profile", "C:", Path("C:settings.yml")]
)
@pytest.mark.parametrize("reader", [select_config_path, load_config, parse_config_yaml])
def test_windows_drive_relative_file_arguments_are_rejected(value, reader) -> None:
    """Reject ambiguous file arguments consistently before filesystem access."""
    with pytest.raises(ValueError, match="drive-relative paths"):
        reader(value)


@pytest.mark.skipif(os.name != "nt", reason="Windows drive-relative syntax")
def test_windows_absolute_and_ordinary_relative_paths_remain_valid(
    tmp_path: Path,
) -> None:
    """Keep fully qualified paths and ordinary relative paths supported."""
    result = parse_yaml(tmp_path, "rimworld_path: C:/game\nmods_path: game\n")
    assert result.value.rimworld_path == Path("C:/game")
    assert result.value.mods_path == result.path.parent / "game"
    assert select_config_path("C:/rimpack-test-missing/settings.yml").is_absolute()


@pytest.mark.skipif(os.name == "nt", reason="POSIX literal path spelling")
def test_drive_relative_looking_text_is_literal_on_posix(tmp_path: Path) -> None:
    """Do not impose Windows drive syntax on POSIX filenames."""
    result = parse_yaml(tmp_path, "mods_path: C:game\n")
    assert result.value.mods_path == result.path.parent / "C:game"


@pytest.mark.parametrize("prefix", ["\u00a0", "\u2003"])
def test_non_yaml_indentation_does_not_turn_scalar_roots_into_comments(
    tmp_path: Path, prefix: str
) -> None:
    """Recognize comment indentation without stripping arbitrary Unicode text."""
    with pytest.raises(ConfigParseError):
        parse_yaml(tmp_path, f"{prefix}# scalar, not a comment\n")


@pytest.mark.parametrize("field", ["mods_path", "unknown"])
def test_out_of_range_unicode_yaml_escapes_are_parse_errors(
    tmp_path: Path, field: str
) -> None:
    """Wrap malformed escapes even when their field would otherwise be ignored."""
    with pytest.raises(ConfigParseError, match="invalid Unicode escape"):
        parse_yaml(tmp_path, field + ': "\\U00110000"\n')


def test_unrelated_loader_value_errors_are_not_hidden(tmp_path: Path, monkeypatch):
    """Avoid treating arbitrary loader implementation failures as invalid YAML."""
    path = write_config(tmp_path, "mods_path: game\n")

    def broken_loader(*args, **kwargs):
        """Simulate an unrelated internal exception with a matching message."""
        raise ValueError("chr() arg not in range(0x110000)")

    monkeypatch.setattr(config, "load", broken_loader)
    with pytest.raises(ValueError) as error:
        parse_config_yaml(path)
    assert not isinstance(error.value, ConfigParseError)


def test_settings_defaults_are_unconfigured_and_immutable() -> None:
    """Keep optional overrides absent and extra discovery roots in a tuple."""
    settings = Settings()

    assert is_dataclass(settings)
    assert all(getattr(settings, field) is None for field in _PATH_FIELDS)
    assert settings.extra_mod_paths == ()
    assert settings.effective_data_path is None
    assert settings.effective_mods_path is None
    with pytest.raises(FrozenInstanceError):
        settings.rimworld_path = Path("changed")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        settings.extra_mod_paths = ()  # type: ignore[misc]


def test_direct_settings_validate_paths_and_freeze_input_collections() -> None:
    """Convert accepted strings to Paths and copy mutable extra-root inputs."""
    extras = ["mods/first", Path("mods/second"), "mods/first"]
    settings = Settings(
        rimworld_path="game",  # type: ignore[arg-type]
        workshop_path=Path("workshop"),
        data_path="alternate-data",  # type: ignore[arg-type]
        mods_path="alternate-mods",  # type: ignore[arg-type]
        extra_mod_paths=extras,  # type: ignore[arg-type]
    )
    extras.append("later")

    assert settings.rimworld_path == Path("game")
    assert settings.workshop_path == Path("workshop")
    assert settings.data_path == Path("alternate-data")
    assert settings.mods_path == Path("alternate-mods")
    assert settings.extra_mod_paths == (
        Path("mods/first"),
        Path("mods/second"),
        Path("mods/first"),
    )
    assert isinstance(settings.extra_mod_paths, tuple)


@pytest.mark.parametrize("field", _PATH_FIELDS)
@pytest.mark.parametrize("value", ["", "   ", "\t\n", "bad\x00path", 1, True])
def test_direct_settings_reject_invalid_path_inputs(field: str, value: object) -> None:
    """Validate every direct optional path rather than coercing malformed values."""
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", _PATH_FIELDS)
def test_direct_settings_accept_none_for_unset_overrides(field: str) -> None:
    """Allow absent optional paths in the Python API without inventing defaults."""
    settings = Settings(**{field: None})

    assert getattr(settings, field) is None


@pytest.mark.parametrize("value", [None, " ", "mods", 1, [""], ["\x00"]])
def test_direct_extra_mod_paths_reject_invalid_collections(value: object) -> None:
    """Only an exactly empty scalar is an alternate empty-list spelling."""
    with pytest.raises(ValidationError):
        Settings(extra_mod_paths=value)  # type: ignore[arg-type]


def test_direct_extra_mod_paths_accept_emptyable_list_spellings() -> None:
    """Apply the shared EmptyableList behavior to direct Settings construction."""
    assert Settings(extra_mod_paths="").extra_mod_paths == ()  # type: ignore[arg-type]
    assert Settings(extra_mod_paths=[]).extra_mod_paths == ()  # type: ignore[arg-type]
    assert Settings(extra_mod_paths=()).extra_mod_paths == ()
    with pytest.raises(ValidationError):
        Settings(unknown="ignored only in YAML")  # type: ignore[call-arg]


def test_effective_paths_use_independent_overrides_without_filesystem_access(
    tmp_path: Path, monkeypatch
) -> None:
    """Derive Data/Mods lexically and retain unavailable explicit overrides."""
    game = tmp_path / "unavailable-game"
    data = tmp_path / "unavailable-data"
    mods = tmp_path / "unavailable-mods"

    def forbidden_access(*args, **kwargs):
        """Fail if effective-path properties inspect or resolve a filesystem path."""
        raise AssertionError("effective paths must be purely lexical")

    monkeypatch.setattr(Path, "stat", forbidden_access)
    monkeypatch.setattr(Path, "resolve", forbidden_access)

    derived = Settings(rimworld_path=game)
    assert derived.data_path is None and derived.mods_path is None
    assert derived.effective_data_path == game / "Data"
    assert derived.effective_mods_path == game / "Mods"
    data_override = Settings(rimworld_path=game, data_path=data)
    assert data_override.effective_data_path == data
    assert data_override.effective_mods_path == game / "Mods"
    mods_override = Settings(rimworld_path=game, mods_path=mods)
    assert mods_override.effective_data_path == game / "Data"
    assert mods_override.effective_mods_path == mods
    independent = Settings(data_path=data, mods_path=mods)
    assert independent.effective_data_path == data
    assert independent.effective_mods_path == mods


def test_parses_all_fields_and_resolves_relative_paths(tmp_path: Path) -> None:
    """Anchor every YAML path field to the selected file, retaining list order."""
    result = parse_yaml(
        tmp_path,
        "rimworld_path: game\n"
        "workshop_path: workshop\n"
        "data_path: data\n"
        "mods_path: mods\n"
        "extra_mod_paths:\n"
        "  - extra/first\n"
        "  - extra/second\n"
        "  - extra/first\n",
    )
    base = tmp_path / "profile"

    assert result.path == base / "settings.yml"
    assert result.value == Settings(
        rimworld_path=base / "game",
        workshop_path=base / "workshop",
        data_path=base / "data",
        mods_path=base / "mods",
        extra_mod_paths=(
            base / "extra/first",
            base / "extra/second",
            base / "extra/first",
        ),
    )
    assert result.diagnostics == ()


@pytest.mark.parametrize("blank", ["", "''", '""'])
def test_blank_extra_mod_paths_are_empty_tuples(tmp_path: Path, blank: str) -> None:
    """Normalize empty scalar collection spellings without relaxing path values."""
    result = parse_yaml(tmp_path, f"extra_mod_paths: {blank} # empty roots\n")

    assert result.value == Settings()
    assert result.diagnostics == ()


def test_omitted_fields_use_schema_defaults(tmp_path: Path) -> None:
    """Omitted fields stay absent even when an effective path can be derived."""
    result = parse_yaml(tmp_path, "rimworld_path: game\n")
    game = tmp_path / "profile" / "game"

    assert result.value.rimworld_path == game
    assert result.value.workshop_path is None
    assert result.value.data_path is None
    assert result.value.mods_path is None
    assert result.value.extra_mod_paths == ()
    assert result.value.effective_data_path == game / "Data"
    assert result.value.effective_mods_path == game / "Mods"


@pytest.mark.parametrize("field", (*_PATH_FIELDS, "extra_mod_paths"))
@pytest.mark.parametrize("scalar", ["123", "00123", "true", "false", "yes", "null"])
def test_yaml_scalar_words_and_digits_remain_lexical_paths(
    tmp_path: Path, field: str, scalar: str
) -> None:
    """Prevent implicit YAML boolean, null, or numeric typing in path strings."""
    if field == "extra_mod_paths":
        source = f"extra_mod_paths:\n  - {scalar}\n"
    else:
        source = f"{field}: {scalar}\n"
    settings = parse_yaml(tmp_path, source).value
    expected = tmp_path / "profile" / scalar

    if field == "extra_mod_paths":
        assert settings.extra_mod_paths == (expected,)
    else:
        assert getattr(settings, field) == expected


@pytest.mark.parametrize("field", (*_PATH_FIELDS, "extra_mod_paths"))
@pytest.mark.parametrize("value", ["", "''", '""', '"   "', '"\\t"', '"bad\\0path"'])
def test_yaml_paths_reject_blank_whitespace_and_nul(
    tmp_path: Path, field: str, value: str
) -> None:
    """Reject malformed supplied paths, including entries in the extra-root list."""
    if field == "extra_mod_paths":
        source = f"extra_mod_paths:\n  - {value}\n"
    else:
        source = f"{field}: {value}\n"

    with pytest.raises(ConfigParseError):
        parse_yaml(tmp_path, source)


@pytest.mark.parametrize("field", _PATH_FIELDS)
def test_yaml_optional_path_fields_cannot_be_sequences(
    tmp_path: Path, field: str
) -> None:
    """Require a scalar in every optional path field."""
    with pytest.raises(ConfigParseError):
        parse_yaml(tmp_path, f"{field}:\n  - not-a-scalar\n")


@pytest.mark.parametrize(
    "source",
    [
        "extra_mod_paths: null\n",
        "extra_mod_paths: not-a-list\n",
        "extra_mod_paths: ' '\n",
        "extra_mod_paths:\n  nested: not-a-list\n",
        "extra_mod_paths:\n  - nested: not-a-path\n",
        "rimworld_path:\n  nested: not-a-path\n",
    ],
)
def test_rejects_invalid_recognized_field_shapes(tmp_path: Path, source: str) -> None:
    """Malformed recognized fields are errors, not discarded warnings."""
    with pytest.raises(ConfigParseError):
        parse_yaml(tmp_path, source)


def test_absolute_paths_tilde_and_environment_expressions(
    tmp_path: Path, monkeypatch
) -> None:
    """Expand the current user's tilde but never expand environment variables."""
    home = tmp_path / "home"
    set_home(monkeypatch, home)
    monkeypatch.setenv("RIMPACK_TEST_ROOT", str(tmp_path / "expanded"))
    absolute = tmp_path / "absolute-missing"
    result = parse_yaml(
        tmp_path,
        f"rimworld_path: '{absolute.as_posix()}'\n"
        "workshop_path: ~/workshop\n"
        "extra_mod_paths:\n"
        "  - ~/mods\n"
        "  - $RIMPACK_TEST_ROOT/mods\n"
        "  - '%RIMPACK_TEST_ROOT%/mods'\n",
    )
    base = tmp_path / "profile"

    assert result.value.rimworld_path == absolute
    assert result.value.workshop_path == home / "workshop"
    assert result.value.extra_mod_paths == (
        home / "mods",
        base / "$RIMPACK_TEST_ROOT" / "mods",
        base / "%RIMPACK_TEST_ROOT%" / "mods",
    )
    assert not absolute.exists()


def test_meaningful_spaces_comments_and_windows_path_text(tmp_path: Path) -> None:
    """Preserve meaningful spaces and host-native path syntax without trimming."""
    result = parse_yaml(
        tmp_path,
        "# settings comment\n"
        "rimworld_path: ' game with spaces '\n"
        r"workshop_path: 'D:\Steam\workshop\content\294100'"
        "\n"
        "extra_mod_paths:\n"
        "  - >-\n"
        "    extra mods\n"
        "    collection\n"
        "  - local # ignored comment\n",
    )
    base = tmp_path / "profile"
    windows_path = Path(r"D:\Steam\workshop\content\294100")
    expected_workshop = (
        windows_path if windows_path.is_absolute() else base / windows_path
    )

    assert result.value.rimworld_path == base / " game with spaces "
    assert result.value.workshop_path == expected_workshop
    assert result.value.extra_mod_paths == (
        base / "extra mods collection",
        base / "local",
    )


def test_relative_file_arguments_become_absolute_and_ignore_later_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    """Make result paths absolute and keep values tied to the selected file."""
    path = write_config(tmp_path, "rimworld_path: game\nextra_mod_paths:\n  - mods\n")
    other = tmp_path / "different-cwd"
    other.mkdir()
    monkeypatch.chdir(tmp_path)

    relative_result = parse_config_yaml(Path("profile") / "settings.yml")
    monkeypatch.chdir(other)
    absolute_result = parse_config_yaml(path)

    assert relative_result == absolute_result
    assert relative_result.path == path
    assert relative_result.value.rimworld_path == path.parent / "game"
    assert relative_result.value.extra_mod_paths == (path.parent / "mods",)


def test_parser_does_not_resolve_configured_targets(
    tmp_path: Path, monkeypatch
) -> None:
    """Load unavailable targets without calling symlink resolution or discovery."""
    path = write_config(
        tmp_path, "rimworld_path: absent\nextra_mod_paths:\n  - missing\n"
    )

    def forbidden_resolution(*args, **kwargs):
        """Reject filesystem resolution of either the source or configured values."""
        raise AssertionError("config parsing must use lexical path anchoring")

    monkeypatch.setattr(Path, "resolve", forbidden_resolution)
    result = parse_config_yaml(path)

    assert result.value.rimworld_path == path.parent / "absent"
    assert result.value.extra_mod_paths == (path.parent / "missing",)


def test_file_symlink_keeps_lexical_parent_for_relative_settings(
    tmp_path: Path,
) -> None:
    """A selected file symlink anchors values beside the link, not its target."""
    actual = write_config(tmp_path, "rimworld_path: game\n")
    selected = tmp_path / "link-profile" / "custom.yaml"
    selected.parent.mkdir()
    make_symlink(selected, actual)

    result = parse_config_yaml(selected)

    assert result.path == selected
    assert result.value.rimworld_path == selected.parent / "game"
    assert select_config_path(selected) == selected
    assert load_config(selected) == result


def test_directory_symlink_keeps_lexical_selected_directory(tmp_path: Path) -> None:
    """Directory selection does not replace a symlink spelling with its target."""
    actual = write_config(tmp_path, "mods_path: local\n")
    selected_directory = tmp_path / "linked-profile"
    make_symlink(selected_directory, actual.parent, directory=True)
    selected_file = selected_directory / "settings.yml"

    assert select_config_path(selected_directory) == selected_file
    result = load_config(selected_directory)
    assert result.path == selected_file
    assert result.value.mods_path == selected_directory / "local"


def test_unknown_fields_are_ignored_with_ordered_structured_diagnostics(
    tmp_path: Path,
) -> None:
    """Keep recognized settings and warn for every unknown root key in order."""
    result = parse_yaml(
        tmp_path,
        "workhop_path: typo\n"
        "rimworld_path: game\n"
        "legacy:\n"
        "  nested:\n"
        "    - ignored\n"
        "another_unknown:\n",
    )

    assert result.value == Settings(rimworld_path=tmp_path / "profile" / "game")
    assert result.diagnostics == (
        UnknownConfigFieldDiagnostic("workhop_path"),
        UnknownConfigFieldDiagnostic("legacy"),
        UnknownConfigFieldDiagnostic("another_unknown"),
    )
    assert render_diagnostics(result.diagnostics) == (
        "- Ignored config field 'workhop_path'\n"
        "- Ignored config field 'legacy'\n"
        "- Ignored config field 'another_unknown'"
    )


def test_unknown_only_mapping_uses_defaults(tmp_path: Path) -> None:
    """An unknown-only mapping still returns default settings and its warning."""
    result = parse_yaml(tmp_path, "old_setting: ignored\n")

    assert result.value == Settings()
    assert result.diagnostics == (UnknownConfigFieldDiagnostic("old_setting"),)


def test_invalid_known_field_is_not_hidden_by_unknown_fields(tmp_path: Path) -> None:
    """Never return a partially successful result when a known value is invalid."""
    with pytest.raises(ConfigParseError):
        parse_yaml(tmp_path, "unknown: warning\nrimworld_path: ''\n")


def test_load_results_and_unknown_diagnostics_are_frozen(tmp_path: Path) -> None:
    """Prevent later mutation of the parsed snapshot and warning payloads."""
    result = parse_yaml(tmp_path, "unknown: ignored\n")
    diagnostic = result.diagnostics[0]

    assert is_dataclass(result)
    assert isinstance(result.diagnostics, tuple)
    assert isinstance(diagnostic, UnknownConfigFieldDiagnostic)
    assert diagnostic.name == "unknown"
    with pytest.raises(FrozenInstanceError):
        result.value = Settings()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.path = tmp_path  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.diagnostics = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        diagnostic.name = "changed"  # type: ignore[misc]


def test_unknown_config_field_renderer_escapes_without_mutating_payload() -> None:
    """Use quoted diagnostic display while retaining the exact unknown field name."""
    name = "first\nsecond\t\x01"
    diagnostic = UnknownConfigFieldDiagnostic(name)

    assert str(diagnostic) == ("- Ignored config field 'first\\nsecond\\t\\u0001'")
    assert diagnostic.name == name


@pytest.mark.parametrize(
    "source",
    ["", "\n", "  \n\t\n", "# only a comment\n\n  # still empty\n"],
)
@pytest.mark.parametrize("bom", [False, True])
def test_blank_and_comment_only_documents_use_defaults(
    tmp_path: Path, source: str, bom: bool
) -> None:
    """Treat valid empty documents as default settings, with or without a BOM."""
    path = write_config(tmp_path, source)
    encoded = source.encode("utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + encoded if bom else encoded)
    original = path.read_bytes()

    result = parse_config_yaml(path)

    assert result == ConfigLoadResult(Settings(), path, ())
    assert load_config(path) == result
    assert path.read_bytes() == original


@pytest.mark.parametrize("source", ["plain scalar root\n", "- sequence root\n"])
def test_rejects_nonmapping_documents(tmp_path: Path, source: str) -> None:
    """Require mappings for nonempty documents rather than scalar or list roots."""
    with pytest.raises(ConfigParseError) as error:
        parse_yaml(tmp_path, source)

    assert error.value.path == tmp_path / "profile" / "settings.yml"
    assert error.value.location == "$"


@pytest.mark.parametrize(
    "source",
    [
        "%YAML 1.3\n---\nmods_path: game\n",
        "%YAML 1.0\n---\nmods_path: game\n",
        "?\n  - x\n  - y\n: value\n",
        "unknown:\n  ?\n    - x\n    - y\n  : value\n",
        "extra_mod_paths: []\n",
        "unknown: {nested: value}\n",
        "rimworld_path: !!str game\n",
        "rimworld_path: &game game\n",
        "rimworld_path: *game\n",
        "rimworld_path: first\nrimworld_path: second\n",
        "unknown: first\nunknown: second\n",
        "unknown:\n  nested: first\n  nested: duplicate\n",
        "rimworld_path: first\n---\nrimworld_path: second\n",
        "rimworld_path: [\n",
    ],
)
def test_rejects_unsupported_or_malformed_yaml_with_source_marks(
    tmp_path: Path, source: str
) -> None:
    """Enforce StrictYAML syntax even inside fields that will later be ignored."""
    with pytest.raises(ConfigParseError) as error:
        parse_yaml(tmp_path, source)

    assert error.value.path == tmp_path / "profile" / "settings.yml"
    assert error.value.location == "$"
    if source.startswith("%YAML"):
        assert error.value.message.startswith("unsupported YAML version")
        assert error.value.line is None and error.value.column is None
    elif source.startswith("?") or source.startswith("unknown:") and "  ?" in source:
        assert error.value.message == "YAML mapping keys must be scalar strings"
        assert error.value.line is None and error.value.column is None
    else:
        assert error.value.line is not None and error.value.line >= 1
        assert error.value.column is not None and error.value.column >= 1


def test_validation_errors_preserve_structured_pydantic_context(tmp_path: Path) -> None:
    """Aggregate domain errors without discarding their original structured details."""
    with pytest.raises(ConfigParseError) as error:
        parse_yaml(tmp_path, "rimworld_path: ''\nextra_mod_paths:\n  - good\n  - ''\n")

    assert error.value.location == "$"
    assert error.value.line is None and error.value.column is None
    context = error.value.__context__
    assert isinstance(context, ValidationError)
    details = context.errors(
        include_url=False, include_context=False, include_input=False
    )
    assert {tuple(detail["loc"]) for detail in details} == {
        ("rimworld_path",),
        ("extra_mod_paths", 1),
    }
    assert all(detail["type"] == "value_error" for detail in details)


def test_accepts_utf8_bom_and_rejects_invalid_encoding(tmp_path: Path) -> None:
    """Accept an optional UTF-8 BOM and report invalid bytes as a config error."""
    path = write_config(tmp_path, "rimworld_path: game\n")
    path.write_bytes(b"\xef\xbb\xbfrimworld_path: game\n")
    assert parse_config_yaml(path).value.rimworld_path == path.parent / "game"

    path.write_bytes(b"rimworld_path: \xff\n")
    with pytest.raises(ConfigParseError, match="UTF-8") as error:
        parse_config_yaml(path)
    assert error.value.path == path


@pytest.mark.parametrize("character", ["\x00", "\x01", "\x1f"])
def test_invalid_yaml_control_characters_are_config_errors(
    tmp_path: Path, character: str
) -> None:
    """Handle StrictYAML's wrapped ReaderError only for invalid source characters."""
    path = write_config(tmp_path, f"rimworld_path: a{character}b\n")

    with pytest.raises(ConfigParseError) as error:
        parse_config_yaml(path)

    assert error.value.path == path
    assert error.value.location == "$"
    assert error.value.message.startswith("unacceptable character")


@pytest.mark.parametrize("character", ["\x00", "\x01", "\x0b", "\x0c", "\x1c", "\x1f"])
def test_invalid_controls_in_comment_only_documents_are_config_errors(
    tmp_path: Path, character: str
) -> None:
    """Do not let empty-document handling bypass invalid YAML source characters."""
    path = write_config(tmp_path, f"# only a comment{character}\n  # still a comment\n")

    with pytest.raises(ConfigParseError) as error:
        parse_config_yaml(path)

    assert error.value.path == path
    assert error.value.location == "$"
    assert error.value.message.startswith("unacceptable character")


@pytest.mark.parametrize("error", [KeyError((1, 3)), AssertionError(tuple)])
def test_unrelated_yaml_library_errors_are_not_hidden(
    tmp_path: Path, monkeypatch, error: Exception
) -> None:
    """Only translate known StrictYAML failures from their specific call frames."""
    path = write_config(tmp_path, "rimworld_path: game\n")

    def broken_loader(*args, **kwargs):
        """Raise a matching exception without a StrictYAML-origin traceback."""
        raise error

    monkeypatch.setattr(config, "load", broken_loader)
    with pytest.raises(type(error)) as caught:
        parse_config_yaml(path)
    assert caught.value is error


def test_unrelated_internal_attribute_errors_are_not_hidden(
    tmp_path: Path, monkeypatch
):
    """The narrow StrictYAML workaround must not disguise unrelated parser bugs."""
    path = write_config(tmp_path, "rimworld_path: game\n")

    def broken_loader(*args, **kwargs):
        """Model an unrelated loader AttributeError without ReaderError context."""
        raise AttributeError("unrelated parser bug")

    monkeypatch.setattr(config, "load", broken_loader)
    with pytest.raises(AttributeError, match="unrelated parser bug"):
        parse_config_yaml(path)


def test_excessive_yaml_nesting_is_a_controlled_config_error(tmp_path: Path) -> None:
    """Translate recursion failures even when deeply nested values are unknown."""
    depth = 256
    lines = ["unknown:"]
    lines.extend(" " * (2 * (level + 1)) + "nested:" for level in range(depth))
    lines.append(" " * (2 * (depth + 1)) + "value")

    with pytest.raises(ConfigParseError) as error:
        parse_yaml(tmp_path, "\n".join(lines) + "\n")

    assert error.value.path == tmp_path / "profile" / "settings.yml"
    assert error.value.location == "$"


def test_default_selection_and_missing_load_do_not_create_settings(
    tmp_path: Path, monkeypatch
) -> None:
    """Only an absent implicit default becomes an empty read-only result."""
    home = tmp_path / "home"
    home.mkdir()
    set_home(monkeypatch, home)
    expected = home / ".rimpack" / "settings.yml"

    assert select_config_path() == expected
    assert select_config_path(None) == expected
    result = load_config()
    assert result.path == expected
    assert result.value == Settings()
    assert result.diagnostics == ()
    assert not expected.parent.exists()


def test_default_load_reads_existing_file(tmp_path: Path, monkeypatch) -> None:
    """Read an existing implicit default instead of supplying empty settings."""
    set_home(monkeypatch, tmp_path)
    path = tmp_path / ".rimpack" / "settings.yml"
    path.parent.mkdir()
    path.write_text("rimworld_path: game\n", encoding="utf-8")

    assert load_config() == parse_config_yaml(path)


@pytest.mark.parametrize(
    "name", ["custom.yml", "custom.yaml", "arbitrary.txt", "settings"]
)
def test_selection_reads_existing_regular_files_regardless_of_extension(
    tmp_path: Path, name: str
) -> None:
    """Filesystem file type takes precedence over nonexistent-path extension hints."""
    path = tmp_path / name
    path.write_text("mods_path: local\n", encoding="utf-8")

    assert select_config_path(path) == path
    assert load_config(path).value.mods_path == tmp_path / "local"


@pytest.mark.parametrize("name", ["profile", "profile.yml", "profile.yaml"])
def test_existing_directories_select_their_settings_file(tmp_path: Path, name: str):
    """Treat existing directories as folders even when they have YAML extensions."""
    directory = tmp_path / name
    directory.mkdir()
    expected = directory / "settings.yml"

    assert select_config_path(directory) == expected
    with pytest.raises(FileNotFoundError):
        load_config(directory)
    assert not expected.exists()


@pytest.mark.parametrize(
    ("name", "is_file"),
    [
        ("new.yml", True),
        ("new.yaml", True),
        ("profile", False),
        ("profile.txt", False),
    ],
)
def test_nonexistent_paths_use_yaml_extension_hints(
    tmp_path: Path, name: str, is_file: bool
) -> None:
    """Select a hinted YAML file or a folder's settings without creating either."""
    path = tmp_path / name
    expected = path if is_file else path / "settings.yml"

    assert select_config_path(path) == expected
    with pytest.raises(FileNotFoundError):
        load_config(path)
    assert not path.exists()


def test_selection_expands_tilde_and_anchors_relative_arguments_to_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    """Keep config argument resolution separate from paths inside the selected file."""
    home = tmp_path / "home"
    work = tmp_path / "working"
    work.mkdir()
    set_home(monkeypatch, home)
    monkeypatch.chdir(work)

    assert select_config_path("~/other/custom.yaml") == home / "other" / "custom.yaml"
    assert select_config_path("relative/custom.yml") == work / "relative" / "custom.yml"
    assert (
        select_config_path("relative/profile") == work / "relative/profile/settings.yml"
    )


def test_selection_does_not_expand_environment_expressions(
    tmp_path: Path, monkeypatch
) -> None:
    """Treat environment-variable spellings received from the caller as path text."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIMPACK_TEST_CONFIG", str(tmp_path / "expanded"))

    assert select_config_path("$RIMPACK_TEST_CONFIG/custom.yml") == (
        tmp_path / "$RIMPACK_TEST_CONFIG" / "custom.yml"
    )
    assert select_config_path("%RIMPACK_TEST_CONFIG%/custom.yml") == (
        tmp_path / "%RIMPACK_TEST_CONFIG%" / "custom.yml"
    )


def test_alternative_config_is_not_merged_with_or_replaced_by_default(
    tmp_path: Path, monkeypatch
) -> None:
    """Explicit files replace the default completely and omitted fields use defaults."""
    set_home(monkeypatch, tmp_path)
    default = tmp_path / ".rimpack" / "settings.yml"
    default.parent.mkdir()
    default.write_text("rimworld_path: default-game\n", encoding="utf-8")
    alternative = write_config(tmp_path, "workshop_path: alternative-workshop\n")

    result = load_config(alternative)

    assert result.path == alternative
    assert result.value == Settings(
        workshop_path=alternative.parent / "alternative-workshop"
    )
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yml")


def test_explicit_missing_default_path_is_an_error(tmp_path: Path, monkeypatch) -> None:
    """Selecting the default spelling explicitly does not permit absent settings."""
    set_home(monkeypatch, tmp_path)
    default = tmp_path / ".rimpack" / "settings.yml"

    with pytest.raises(FileNotFoundError):
        load_config(default)
    with pytest.raises(FileNotFoundError):
        parse_config_yaml(default)
    assert not default.parent.exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_existing_invalid_default_is_never_treated_as_missing(
    tmp_path: Path, monkeypatch, explicit: bool
) -> None:
    """Malformed existing settings are errors for both default and explicit loading."""
    set_home(monkeypatch, tmp_path)
    path = tmp_path / ".rimpack" / "settings.yml"
    path.parent.mkdir()
    path.write_text("rimworld_path: ''\n", encoding="utf-8")

    with pytest.raises(ConfigParseError):
        load_config(path if explicit else None)


@pytest.mark.parametrize("explicit", [False, True])
def test_existing_unreadable_default_keeps_filesystem_error(
    tmp_path: Path, monkeypatch, explicit: bool
) -> None:
    """Do not replace read failures with defaults, parser errors, or another file."""
    set_home(monkeypatch, tmp_path)
    path = tmp_path / ".rimpack" / "settings.yml"
    path.parent.mkdir()
    path.write_text("rimworld_path: game\n", encoding="utf-8")
    original_read = Path.read_text

    def unreadable(source: Path, *args, **kwargs):
        """Simulate a permission failure for the selected settings file only."""
        if source == path:
            raise PermissionError("test unreadable settings")
        return original_read(source, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(PermissionError, match="test unreadable settings"):
        load_config(path if explicit else None)


@pytest.mark.parametrize("explicit", [False, True])
def test_read_file_not_found_error_with_present_target_is_not_missing_config(
    tmp_path: Path, monkeypatch, explicit: bool
) -> None:
    """Preserve a failed read when a post-failure check still finds the file."""
    set_home(monkeypatch, tmp_path)
    path = tmp_path / ".rimpack" / "settings.yml"
    path.parent.mkdir()
    path.write_text("rimworld_path: game\n", encoding="utf-8")
    original_read = Path.read_text

    def failed_read(source: Path, *args, **kwargs):
        """Simulate a read-time missing-file error without removing the target."""
        if source == path:
            raise FileNotFoundError("test read race with present target")
        return original_read(source, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failed_read)
    with pytest.raises(FileNotFoundError, match="test read race with present target"):
        load_config(path if explicit else None)
    assert path.is_file()


@pytest.mark.parametrize("explicit", [False, True])
def test_file_disappearing_before_read_obeys_default_missing_policy(
    tmp_path: Path, monkeypatch, explicit: bool
) -> None:
    """Use defaults for a vanished implicit file but never an explicit one."""
    set_home(monkeypatch, tmp_path)
    path = tmp_path / ".rimpack" / "settings.yml"
    path.parent.mkdir()
    path.write_text("rimworld_path: game\n", encoding="utf-8")
    original_read = Path.read_text

    def disappearing_read(source: Path, *args, **kwargs):
        """Remove the file after its initial type check but before reading it."""
        if source == path:
            path.unlink()
        return original_read(source, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", disappearing_read)
    if explicit:
        with pytest.raises(FileNotFoundError):
            load_config(path)
    else:
        assert load_config() == ConfigLoadResult(Settings(), path, ())
    assert not path.exists()


def test_implicit_default_directory_is_not_missing_settings(
    tmp_path: Path, monkeypatch
):
    """A directory at the default file location must fail instead of using defaults."""
    set_home(monkeypatch, tmp_path)
    path = tmp_path / ".rimpack" / "settings.yml"
    path.mkdir(parents=True)

    with pytest.raises(OSError):
        load_config()


@pytest.mark.parametrize("name", ["dangling.yml", "dangling-profile"])
def test_dangling_symlinks_are_errors_not_nonexistent_path_hints(
    tmp_path: Path, name: str
) -> None:
    """Reject broken existing links rather than inferring a settings folder/file."""
    link = tmp_path / name
    make_symlink(link, tmp_path / "missing-target")

    with pytest.raises(OSError):
        select_config_path(link)
    with pytest.raises(OSError):
        load_config(link)


def test_dangling_default_symlink_is_not_an_absent_default(tmp_path: Path, monkeypatch):
    """Never turn a broken default-file link into a successful empty configuration."""
    set_home(monkeypatch, tmp_path)
    link = tmp_path / ".rimpack" / "settings.yml"
    link.parent.mkdir()
    make_symlink(link, tmp_path / "missing-target")

    with pytest.raises(OSError):
        load_config()


def test_dangling_default_ancestor_is_not_an_absent_default(
    tmp_path: Path, monkeypatch
) -> None:
    """A broken configuration-directory link is an error, not a missing default file."""
    set_home(monkeypatch, tmp_path)
    directory = tmp_path / ".rimpack"
    make_symlink(directory, tmp_path / "missing-directory", directory=True)

    with pytest.raises(FileNotFoundError):
        load_config()


@pytest.mark.parametrize(
    ("mode", "is_junction"), [(stat.S_IFLNK, False), (stat.S_IFDIR, True)]
)
def test_dangling_default_ancestor_links_are_detected_without_privileges(
    tmp_path: Path, monkeypatch, mode: int, is_junction: bool
) -> None:
    """Exercise dangling ancestor checks on hosts that cannot create symlinks."""
    set_home(monkeypatch, tmp_path)
    directory = tmp_path / ".rimpack"
    path = directory / "settings.yml"
    original_stat = Path.stat
    original_lstat = Path.lstat

    def missing_stat(source: Path, *args, **kwargs):
        """Model a missing file beneath a directory link whose target is missing."""
        if source in (path, directory):
            raise FileNotFoundError("test dangling ancestor")
        return original_stat(source, *args, **kwargs)

    def link_lstat(source: Path, *args, **kwargs):
        """Report the ancestor link itself while keeping its child file absent."""
        if source == path:
            raise FileNotFoundError("test missing settings beneath link")
        if source == directory:
            return SimpleNamespace(st_mode=mode)
        return original_lstat(source, *args, **kwargs)

    def junction_check(source: Path) -> bool:
        """Model a directory junction while leaving normal ancestors untouched."""
        return source == directory and is_junction

    monkeypatch.setattr(Path, "stat", missing_stat)
    monkeypatch.setattr(Path, "lstat", link_lstat)
    monkeypatch.setattr(Path, "is_junction", junction_check, raising=False)
    with pytest.raises(FileNotFoundError, match="test dangling ancestor"):
        load_config()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junctions")
def test_dangling_default_windows_junction_is_not_absent(
    tmp_path: Path, monkeypatch
) -> None:
    """Treat an actual broken Windows directory junction as a filesystem error."""
    home = tmp_path / "home"
    home.mkdir()
    junction = home / ".rimpack"
    missing_target = home / "missing-directory"
    missing_target.mkdir()
    completed = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(missing_target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"could not create test junction: {completed.stderr}")
    missing_target.rmdir()
    assert junction.is_junction()
    set_home(monkeypatch, home)

    with pytest.raises(FileNotFoundError):
        load_config()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are unavailable")
def test_special_fifo_is_rejected_without_reading_or_blocking(tmp_path: Path) -> None:
    """Reject an existing named pipe before a YAML read could wait for a writer."""
    path = tmp_path / "settings.yml"
    os.mkfifo(path)

    with pytest.raises(OSError):
        select_config_path(path)
    with pytest.raises(OSError):
        load_config(path)


@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="Unix sockets are unavailable"
)
def test_special_socket_is_rejected_as_a_settings_target(tmp_path: Path) -> None:
    """An existing socket must not be mistaken for a regular file or a directory."""
    path = tmp_path / "settings.yml"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        try:
            server.bind(str(path))
        except OSError as error:
            pytest.skip(f"filesystem sockets are unavailable: {error}")
        with pytest.raises(OSError):
            select_config_path(path)
        with pytest.raises(OSError):
            load_config(path)
