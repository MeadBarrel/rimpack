"""Tests for bounded Windows Steam library and RimWorld path discovery."""

import os
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType

import pytest

from rimpack.sdk import installation_discovery as steam_paths
from rimpack.sdk.installation_discovery import (
    RimWorldSteamInstallation,
    _discover_from_roots,
    discover_rimworld_steam_installations,
)


def _quoted(value: str) -> str:
    """Escape a string as a quoted KeyValues scalar."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_manifest(
    library: Path,
    *,
    app_id: str = "294100",
    install_dir: str = "RimWorld",
    root_name: str = "AppState",
) -> Path:
    """Write the minimal Steam app manifest needed by discovery tests."""
    steamapps = library / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    manifest = steamapps / "appmanifest_294100.acf"
    manifest.write_text(
        f'{_quoted(root_name)} {{\n'
        f'  "appid" "{app_id}"\n'
        f'  "installdir" "{install_dir}"\n'
        "}\n",
        encoding="utf-8",
    )
    return manifest


def _make_install(
    library: Path,
    *,
    install_dir: str = "RimWorld",
    workshop: bool = True,
) -> Path:
    """Create a valid fake RimWorld install and optionally its Workshop root."""
    game = library / "steamapps" / "common" / install_dir
    game.mkdir(parents=True)
    (game / "RimWorldWin64.exe").write_bytes(b"fake executable")
    (game / "Data").mkdir()
    _write_manifest(library, install_dir=install_dir)
    if workshop:
        (library / "steamapps" / "workshop" / "content" / "294100").mkdir(
            parents=True
        )
    return game


def _write_modern_libraryfolders(client: Path, libraries: list[Path]) -> None:
    """Write modern nested Steam library metadata for temporary library paths."""
    steamapps = client / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    records = [
        f'    "{index}" {{ "path" {_quoted(str(library))} }}'
        for index, library in enumerate(libraries)
    ]
    (steamapps / "libraryfolders.vdf").write_text(
        '"LibraryFolders" {\n' + "\n".join(records) + "\n}\n",
        encoding="utf-8",
    )


def test_client_metadata_finds_separate_library_and_workshop_path(tmp_path: Path):
    """Expand a client's modern library metadata and return both existing paths."""
    client = tmp_path / "client"
    library = tmp_path / "game-library"
    game = _make_install(library)
    _write_modern_libraryfolders(client, [library])

    results = _discover_from_roots([client])

    assert results == (
        RimWorldSteamInstallation(
            game_path=game,
            workshop_path=library / "steamapps" / "workshop" / "content" / "294100",
        ),
    )


def test_workshop_path_is_optional_and_empty_directory_is_valid(tmp_path: Path):
    """Return None for missing Workshop content but include an empty directory."""
    missing_library = tmp_path / "without-workshop"
    missing_game = _make_install(missing_library, workshop=False)
    empty_library = tmp_path / "empty-workshop"
    empty_game = _make_install(empty_library, workshop=False)
    empty_workshop = empty_library / "steamapps" / "workshop" / "content" / "294100"
    empty_workshop.mkdir(parents=True)

    results = _discover_from_roots([missing_library, empty_library])

    by_game = {result.game_path: result.workshop_path for result in results}
    assert by_game == {missing_game: None, empty_game: empty_workshop}


def test_legacy_and_modern_library_entries_find_multiple_installs(tmp_path: Path):
    """Handle legacy scalar and modern nested numeric library records together."""
    client = tmp_path / "client"
    legacy_library = tmp_path / "legacy-library"
    modern_library = tmp_path / "modern-library"
    legacy_game = _make_install(legacy_library)
    modern_game = _make_install(modern_library)
    steamapps = client / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / "libraryfolders.vdf").write_text(
        '"libraryfolders" {\n'
        f'  "0" {_quoted(str(legacy_library))}\n'
        f'  "1" {{ "path" {_quoted(str(modern_library))} }}\n'
        "}\n",
        encoding="utf-8",
    )

    results = _discover_from_roots([client])

    assert {result.game_path for result in results} == {legacy_game, modern_game}
    assert [result.game_path for result in results] == sorted(
        (legacy_game, modern_game),
        key=steam_paths._normalized_path_key,
    )


def test_direct_library_and_repeated_metadata_paths_are_deduplicated(tmp_path: Path):
    """Deduplicate direct candidates and metadata entries by normalized path."""
    library = tmp_path / "SteamLibrary"
    game = _make_install(library)
    duplicate_spelling = library
    if os.name == "nt":
        duplicate_spelling = Path(str(library).swapcase())
    _write_modern_libraryfolders(library, [library, duplicate_spelling])

    results = _discover_from_roots([library, duplicate_spelling])

    assert len(results) == 1
    assert results[0].game_path == game


def test_only_direct_numeric_library_paths_are_trusted(tmp_path: Path):
    """Ignore nested arbitrary path fields rather than treating them as libraries."""
    client = tmp_path / "client"
    unrelated_library = tmp_path / "not-a-library"
    _make_install(unrelated_library)
    steamapps = client / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "libraryfolders.vdf").write_text(
        '"libraryfolders" { "0" { "apps" { "path" '
        f'{_quoted(str(unrelated_library))} }} }}\n',
        encoding="utf-8",
    )

    assert _discover_from_roots([client]) == ()


def test_manifest_fields_must_be_direct_children_of_app_state(tmp_path: Path):
    """Ignore app IDs and install directories nested under unrelated fields."""
    library = tmp_path / "library"
    game = _make_install(library)
    manifest = library / "steamapps" / "appmanifest_294100.acf"
    manifest.write_text(
        '"AppState" { "Other" { "appid" "294100" '
        '"installdir" "RimWorld" } }\n',
        encoding="utf-8",
    )

    assert _discover_from_roots([library]) == ()
    assert game.is_dir()


def test_duplicate_library_indices_are_rejected(tmp_path: Path):
    """Do not trust either path when a numeric library key is duplicated."""
    client = tmp_path / "client"
    first_library = tmp_path / "first-library"
    second_library = tmp_path / "second-library"
    _make_install(first_library)
    _make_install(second_library)
    steamapps = client / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "libraryfolders.vdf").write_text(
        '"libraryfolders" {\n'
        f'  "0" {_quoted(str(first_library))}\n'
        f'  "0" {_quoted(str(second_library))}\n'
        "}\n",
        encoding="utf-8",
    )

    assert _discover_from_roots([client]) == ()


def test_wrong_or_missing_app_id_and_missing_game_markers_are_rejected(
    tmp_path: Path,
):
    """Require the target app ID and named RimWorld executable/data markers."""
    wrong_id_library = tmp_path / "wrong-id"
    wrong_game = _make_install(wrong_id_library)
    _write_manifest(wrong_id_library, app_id="570")

    missing_markers_library = tmp_path / "missing-markers"
    missing_markers_game = missing_markers_library / "steamapps" / "common" / "RimWorld"
    missing_markers_game.mkdir(parents=True)
    (missing_markers_game / "other-game.exe").write_bytes(b"not RimWorld")
    (missing_markers_game / "Data").mkdir()
    _write_manifest(missing_markers_library)

    missing_id_library = tmp_path / "missing-id"
    missing_id_game = _make_install(missing_id_library)
    _write_manifest(missing_id_library, app_id="")

    assert _discover_from_roots(
        [wrong_id_library, missing_markers_library, missing_id_library]
    ) == ()
    assert wrong_game.exists() and missing_id_game.exists()


@pytest.mark.parametrize(
    "install_dir",
    ["../escape", "..\\escape", "C:\\escape", "/escape"],
)
def test_unsafe_manifest_install_directories_are_rejected(
    tmp_path: Path, install_dir: str
):
    """Reject absolute or traversing install-directory values before joining paths."""
    library = tmp_path / "library"
    steamapps = library / "steamapps"
    steamapps.mkdir(parents=True)
    _write_manifest(library, install_dir=install_dir)

    assert _discover_from_roots([library]) == ()


def test_malformed_library_vdf_is_skipped_without_aborting_other_roots(
    tmp_path: Path,
):
    """Ignore one malformed client's metadata while validating a direct library."""
    broken_client = tmp_path / "broken-client"
    (broken_client / "steamapps").mkdir(parents=True)
    (broken_client / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders" { "0" { "path" "unterminated }', encoding="utf-8"
    )
    direct_library = tmp_path / "direct-library"
    direct_game = _make_install(direct_library)

    results = _discover_from_roots([broken_client, direct_library])

    assert [result.game_path for result in results] == [direct_game]


def test_malformed_and_oversized_manifests_are_rejected(tmp_path: Path, monkeypatch):
    """Skip malformed and over-limit app manifests without losing other results."""
    malformed_library = tmp_path / "malformed"
    malformed_game = _make_install(malformed_library)
    malformed_manifest = _write_manifest(malformed_library)
    malformed_manifest.write_text('"AppState" { "appid" "294100"', encoding="utf-8")

    oversized_library = tmp_path / "oversized"
    oversized_game = _make_install(oversized_library)
    _write_manifest(oversized_library)
    monkeypatch.setattr(steam_paths, "_MAX_METADATA_BYTES", 64)
    (oversized_library / "steamapps" / "appmanifest_294100.acf").write_text(
        '"AppState" { "appid" "294100" "installdir" "RimWorld" }\n' + " " * 100,
        encoding="utf-8",
    )

    assert _discover_from_roots([malformed_library, oversized_library]) == ()
    assert malformed_game.exists() and oversized_game.exists()


def test_oversized_library_metadata_is_rejected(tmp_path: Path, monkeypatch):
    """Do not parse libraryfolders metadata after it exceeds the byte cap."""
    client = tmp_path / "client"
    library = tmp_path / "library"
    _make_install(library)
    _write_modern_libraryfolders(client, [library])
    monkeypatch.setattr(steam_paths, "_MAX_METADATA_BYTES", 64)
    metadata = client / "steamapps" / "libraryfolders.vdf"
    metadata.write_text(
        metadata.read_text(encoding="utf-8") + " " * 100,
        encoding="utf-8",
    )

    assert _discover_from_roots([client]) == ()


def test_unreadable_manifest_is_skipped(tmp_path: Path, monkeypatch):
    """Treat metadata read failures as a rejected candidate, not a scan failure."""
    library = tmp_path / "library"
    _make_install(library)
    read_vdf = steam_paths._read_vdf
    manifest = library / "steamapps" / "appmanifest_294100.acf"

    def unreadable(path: Path):
        """Simulate a permission error for this candidate's app manifest."""
        if path == manifest:
            raise PermissionError("test unreadable metadata")
        return read_vdf(path)

    monkeypatch.setattr(steam_paths, "_read_vdf", unreadable)

    assert _discover_from_roots([library]) == ()


def test_discovery_does_not_walk_game_or_workshop_trees(tmp_path: Path, monkeypatch):
    """Validate only named root markers and never enumerate nested mod content."""
    library = tmp_path / "library"
    game = _make_install(library)
    workshop_item = (
        library / "steamapps" / "workshop" / "content" / "294100" / "12345"
    )
    (workshop_item / "Mods").mkdir(parents=True)
    (workshop_item / "Mods" / "fake-game.exe").write_bytes(b"must not be inspected")

    def fail_enumeration(_self, *args, **kwargs):
        """Fail if implementation attempts to list or recursively walk a directory."""
        raise AssertionError("discovery must not enumerate directories")

    monkeypatch.setattr(Path, "iterdir", fail_enumeration)
    monkeypatch.setattr(Path, "glob", fail_enumeration)
    monkeypatch.setattr(Path, "rglob", fail_enumeration)
    monkeypatch.setattr(steam_paths.os, "scandir", fail_enumeration)

    results = _discover_from_roots([library])

    assert results[0].game_path == game
    assert results[0].workshop_path == (
        library / "steamapps" / "workshop" / "content" / "294100"
    )


def test_public_discovery_returns_empty_without_scanning_on_non_windows(monkeypatch):
    """Return no matches on non-Windows without collecting platform candidates."""
    monkeypatch.setattr(steam_paths, "_is_windows", lambda: False)

    def forbidden_candidates():
        """Fail if a non-Windows call tries to inspect Steam roots."""
        raise AssertionError("non-Windows discovery must stop before root discovery")

    monkeypatch.setattr(steam_paths, "_steam_root_candidates", forbidden_candidates)

    assert discover_rimworld_steam_installations() == ()


def test_registry_roots_read_standard_values_and_deduplicate_views(
    tmp_path: Path, monkeypatch
):
    """Read SteamPath and InstallPath from mocked Valve registry hives/views."""
    current_user_root = tmp_path / "current-user-steam"
    machine_root = tmp_path / "machine-steam"
    registry = ModuleType("winreg")
    registry.HKEY_CURRENT_USER = "HKCU"
    registry.HKEY_LOCAL_MACHINE = "HKLM"
    registry.KEY_READ = 1
    registry.KEY_WOW64_64KEY = 256
    registry.KEY_WOW64_32KEY = 512

    def open_key(hive, _subkey, _options, _access):
        """Return the hive label as a context-managed fake registry handle."""
        return nullcontext(hive)

    def query_value(hive, value_name):
        """Return configured roots and emulate absent registry values."""
        if hive == "HKCU" and value_name == "SteamPath":
            return str(current_user_root), 1
        if hive == "HKLM" and value_name == "InstallPath":
            return str(machine_root), 1
        raise FileNotFoundError(value_name)

    registry.OpenKey = open_key
    registry.QueryValueEx = query_value
    monkeypatch.setitem(sys.modules, "winreg", registry)

    assert steam_paths._registry_steam_roots() == (current_user_root, machine_root)


def test_root_candidates_include_environment_and_enumerated_drive_patterns(
    tmp_path: Path, monkeypatch
):
    """Include standard environment roots and fixed paths under logical drives."""
    environment_bases = {
        "ProgramFiles(x86)": tmp_path / "pf86",
        "ProgramFiles": tmp_path / "program-files",
        "ProgramW6432": tmp_path / "program-w6432",
        "USERPROFILE": tmp_path / "profile",
        "LOCALAPPDATA": tmp_path / "local-app-data",
    }
    for name, value in environment_bases.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setattr(steam_paths, "_registry_steam_roots", lambda: ())
    drive = tmp_path / "logical-drive"
    monkeypatch.setattr(steam_paths, "_logical_drive_roots", lambda: (drive,))

    candidates = set(steam_paths._steam_root_candidates())
    expected_environment_roots = {
        environment_bases["ProgramFiles(x86)"] / "Steam",
        environment_bases["ProgramFiles"] / "Steam",
        environment_bases["ProgramW6432"] / "Steam",
        environment_bases["USERPROFILE"] / "AppData" / "Local" / "Steam",
        environment_bases["LOCALAPPDATA"] / "Programs" / "Steam",
    }
    expected_drive_roots = {
        drive / "Steam",
        drive / "Program Files (x86)" / "Steam",
        drive / "Program Files" / "Steam",
        drive / "Games" / "Steam",
    }

    assert expected_environment_roots | expected_drive_roots <= candidates


def test_public_discovery_uses_windows_candidate_roots(tmp_path: Path, monkeypatch):
    """Exercise the public Windows branch with an isolated Steam library root."""
    library = tmp_path / "library"
    game = _make_install(library)
    monkeypatch.setattr(steam_paths, "_is_windows", lambda: True)
    monkeypatch.setattr(steam_paths, "_steam_root_candidates", lambda: (library,))

    assert discover_rimworld_steam_installations() == (
        RimWorldSteamInstallation(
            game_path=game,
            workshop_path=library / "steamapps" / "workshop" / "content" / "294100",
        ),
    )


def test_vdf_parser_enforces_token_and_nesting_limits(monkeypatch):
    """Reject metadata that exceeds either parser resource bound."""
    monkeypatch.setattr(steam_paths, "_MAX_VDF_TOKENS", 3)
    with pytest.raises(steam_paths._VdfParseError, match="too many tokens"):
        steam_paths._parse_vdf('"a" "b" "c" "d"')

    monkeypatch.setattr(steam_paths, "_MAX_VDF_TOKENS", 100)
    monkeypatch.setattr(steam_paths, "_MAX_VDF_NESTING", 1)
    with pytest.raises(steam_paths._VdfParseError, match="nesting is too deep"):
        steam_paths._parse_vdf('"a" { "b" { "c" "d" } }')


def test_game_markers_reject_a_resolved_path_outside_common(
    tmp_path: Path, monkeypatch
):
    """Reject an install directory whose resolved target escapes common."""
    common = tmp_path / "library" / "steamapps" / "common"
    game = common / "RimWorld"
    game.mkdir(parents=True)
    (game / "RimWorldWin64.exe").write_bytes(b"fake executable")
    (game / "Data").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_resolve = Path.resolve

    def resolve(path, *, strict=False):
        """Model a directory symlink whose resolved target is outside common."""
        if path == game:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert not steam_paths._has_rimworld_markers(game, common)
