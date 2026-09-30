"""Discover existing RimWorld installations managed by Steam on Windows.

Discovery reads a bounded amount of Steam metadata and checks explicit game
markers. It does not scan drives, inspect mod trees, cache filesystem state, or
run during SDK import.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Iterable, Literal

APP_ID = "294100"
_MAX_METADATA_BYTES = 1_000_000
_MAX_VDF_TOKENS = 100_000
_MAX_VDF_NESTING = 32
_MAX_LIBRARY_PATHS = 256
_REGISTRY_SUBKEY = r"SOFTWARE\Valve\Steam"

_KNOWN_GAME_EXECUTABLES = ("RimWorldWin64.exe", "RimWorld.exe")
_KNOWN_GAME_DATA_DIRECTORIES = ("Data", "RimWorldWin64_Data")


@dataclass(frozen=True, slots=True)
class RimWorldSteamInstallation:
    """Describe an existing Steam-managed RimWorld installation.

    ``workshop_path`` is the library's Workshop content directory when that
    directory already exists; an empty directory is still a valid result.
    """

    game_path: Path
    workshop_path: Path | None


@dataclass(frozen=True, slots=True)
class _VdfToken:
    """Represent one bounded token emitted by the small KeyValues reader."""

    kind: Literal["string", "open", "close"]
    value: str = ""


@dataclass(frozen=True, slots=True)
class _VdfEntry:
    """Store one KeyValues entry without flattening its nesting context."""

    key: str
    value: str | tuple[_VdfEntry, ...]


class _VdfParseError(ValueError):
    """Identify malformed or over-limit Steam KeyValues metadata."""


def _is_windows() -> bool:
    """Return whether this process is running on native Windows."""
    return os.name == "nt" and sys.platform == "win32"


def _normalized_path_key(path: Path) -> str:
    """Normalize a path for Windows-style, case-insensitive deduplication."""
    return ntpath.normcase(ntpath.normpath(str(path)))


def _add_unique_path(paths: dict[str, Path], path: Path) -> None:
    """Keep the first spelling of an absolute path under its normalized key."""
    try:
        if "\x00" in str(path) or not path.is_absolute():
            return
        key = _normalized_path_key(path)
    except (OSError, ValueError):
        return
    paths.setdefault(key, path)


def _registry_steam_roots() -> tuple[Path, ...]:
    """Read standard Steam root values from the available Windows registry views."""
    try:
        import winreg
    except ImportError:
        return ()

    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    views = [0]
    for name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        view = getattr(winreg, name, 0)
        if view and view not in views:
            views.append(view)

    roots: dict[str, Path] = {}
    for hive in hives:
        for view in views:
            try:
                with winreg.OpenKey(
                    hive,
                    _REGISTRY_SUBKEY,
                    0,
                    winreg.KEY_READ | view,
                ) as key:
                    for value_name in ("SteamPath", "InstallPath"):
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if isinstance(value, str) and value.strip():
                            _add_unique_path(roots, Path(value.strip()))
            except OSError:
                continue
    return tuple(roots.values())


def _logical_drive_roots() -> tuple[Path, ...]:
    """Enumerate Windows logical drive roots without traversing their contents."""
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return ()
    return tuple(
        Path(f"{chr(ord('A') + index)}:\\")
        for index in range(26)
        if mask & (1 << index)
    )


def _steam_root_candidates() -> tuple[Path, ...]:
    """Collect registry, environment, and fixed conventional Steam root paths."""
    candidates: dict[str, Path] = {}
    for root in _registry_steam_roots():
        _add_unique_path(candidates, root)

    environment_roots = (
        ("ProgramFiles(x86)", "Steam"),
        ("ProgramFiles", "Steam"),
        ("ProgramW6432", "Steam"),
        ("USERPROFILE", os.path.join("AppData", "Local", "Steam")),
        ("LOCALAPPDATA", os.path.join("Programs", "Steam")),
    )
    for variable, suffix in environment_roots:
        base = os.environ.get(variable)
        if base:
            _add_unique_path(candidates, Path(base) / suffix)

    for path in (
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
    ):
        _add_unique_path(candidates, path)

    for drive in _logical_drive_roots():
        for suffix in (
            Path("Steam"),
            Path("Program Files (x86)") / "Steam",
            Path("Program Files") / "Steam",
            Path("Games") / "Steam",
        ):
            _add_unique_path(candidates, drive / suffix)
    return tuple(candidates.values())


def _tokenize_vdf(text: str) -> tuple[_VdfToken, ...]:
    """Tokenize quoted or bare KeyValues strings, braces, whitespace, and comments."""
    tokens: list[_VdfToken] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
            continue
        if character == "{":
            tokens.append(_VdfToken("open"))
            index += 1
        elif character == "}":
            tokens.append(_VdfToken("close"))
            index += 1
        elif character == '"':
            index += 1
            value: list[str] = []
            while index < len(text) and text[index] != '"':
                current = text[index]
                if current == "\\":
                    if index + 1 >= len(text):
                        raise _VdfParseError("quoted string ends with an escape")
                    escaped = text[index + 1]
                    if escaped in ('"', "\\"):
                        value.append(escaped)
                    elif escaped == "n":
                        value.append("\n")
                    elif escaped == "t":
                        value.append("\t")
                    else:
                        value.extend(("\\", escaped))
                    index += 2
                else:
                    value.append(current)
                    index += 1
            if index >= len(text):
                raise _VdfParseError("unterminated quoted string")
            index += 1
            tokens.append(_VdfToken("string", "".join(value)))
        else:
            start = index
            while (
                index < len(text)
                and not text[index].isspace()
                and text[index] not in "{}"
                and not text.startswith("//", index)
            ):
                index += 1
            if start == index:
                raise _VdfParseError("unexpected character in metadata")
            tokens.append(_VdfToken("string", text[start:index]))
        if len(tokens) > _MAX_VDF_TOKENS:
            raise _VdfParseError("metadata contains too many tokens")
    return tuple(tokens)


def _parse_vdf_entries(
    tokens: tuple[_VdfToken, ...],
) -> tuple[_VdfEntry, ...]:
    """Parse nested KeyValues entries while retaining direct-child boundaries."""
    position = 0

    def parse_block(depth: int, *, nested: bool) -> tuple[_VdfEntry, ...]:
        """Parse one brace-delimited block or the document's top-level entries."""
        nonlocal position
        if depth > _MAX_VDF_NESTING:
            raise _VdfParseError("metadata nesting is too deep")
        entries: list[_VdfEntry] = []
        while position < len(tokens):
            token = tokens[position]
            if token.kind == "close":
                if not nested:
                    raise _VdfParseError("unexpected closing brace")
                position += 1
                return tuple(entries)
            if token.kind != "string":
                raise _VdfParseError("expected a KeyValues key")
            key = token.value
            position += 1
            if position >= len(tokens):
                raise _VdfParseError("KeyValues key has no value")
            value_token = tokens[position]
            if value_token.kind == "open":
                position += 1
                value: str | tuple[_VdfEntry, ...] = parse_block(
                    depth + 1, nested=True
                )
            elif value_token.kind == "string":
                value = value_token.value
                position += 1
            else:
                raise _VdfParseError("KeyValues key has no value")
            entries.append(_VdfEntry(key, value))
        if nested:
            raise _VdfParseError("unclosed KeyValues block")
        return tuple(entries)

    parsed = parse_block(0, nested=False)
    if position != len(tokens):
        raise _VdfParseError("trailing metadata after the root block")
    return parsed


def _parse_vdf(text: str) -> tuple[_VdfEntry, ...]:
    """Read one bounded VDF document into nested entries or reject malformed text."""
    try:
        return _parse_vdf_entries(_tokenize_vdf(text))
    except RecursionError as error:
        raise _VdfParseError("metadata nesting is too deep") from error


def _read_vdf(path: Path) -> tuple[_VdfEntry, ...]:
    """Read and parse a UTF-8 Steam metadata file subject to the byte-size cap."""
    with path.open("rb") as stream:
        raw = stream.read(_MAX_METADATA_BYTES + 1)
    if len(raw) > _MAX_METADATA_BYTES:
        raise _VdfParseError("metadata exceeds the 1 MB size limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _VdfParseError("metadata is not valid UTF-8") from error
    return _parse_vdf(text)


def _single_named_entry(
    entries: tuple[_VdfEntry, ...], name: str
) -> _VdfEntry | None:
    """Return one uniquely named direct entry, ignoring nested descendants."""
    matches = [entry for entry in entries if entry.key.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else None


def _single_scalar(entries: tuple[_VdfEntry, ...], name: str) -> str | None:
    """Return a unique direct scalar field, rejecting missing or ambiguous values."""
    entry = _single_named_entry(entries, name)
    if entry is None or not isinstance(entry.value, str):
        return None
    return entry.value


def _absolute_metadata_path(raw_path: str) -> Path | None:
    """Convert a nonempty absolute metadata path without accepting relative paths."""
    value = raw_path.strip()
    if not value or "\x00" in value:
        return None
    try:
        path = Path(value)
        if not path.is_absolute():
            return None
    except (OSError, ValueError):
        return None
    return path


def _library_paths(entries: tuple[_VdfEntry, ...]) -> tuple[Path, ...]:
    """Extract legacy and modern library paths only from numeric library records."""
    root = _single_named_entry(entries, "libraryfolders")
    if root is None or not isinstance(root.value, tuple):
        return ()

    paths: dict[str, Path] = {}
    numeric_counts: dict[str, int] = {}
    for entry in root.value:
        if entry.key.isascii() and entry.key.isdecimal():
            numeric_counts[entry.key] = numeric_counts.get(entry.key, 0) + 1
    for entry in root.value:
        if (
            not entry.key.isascii()
            or not entry.key.isdecimal()
            or numeric_counts[entry.key] != 1
        ):
            continue
        if isinstance(entry.value, str):
            raw_path = entry.value
        else:
            raw_path = _single_scalar(entry.value, "path")
            if raw_path is None:
                continue
        library_path = _absolute_metadata_path(raw_path)
        if library_path is not None:
            _add_unique_path(paths, library_path)
        if len(paths) >= _MAX_LIBRARY_PATHS:
            break
    return tuple(paths.values())


def _valid_install_directory(value: str) -> bool:
    """Accept only one safe Windows path component from a Steam app manifest."""
    if not value or value != value.strip() or "\x00" in value:
        return False
    windows_path = PureWindowsPath(value)
    if windows_path.is_absolute() or windows_path.drive or windows_path.root:
        return False
    if len(windows_path.parts) != 1 or windows_path.parts[0] in (".", ".."):
        return False
    if any(character in value for character in '<>:"/\\|?*'):
        return False
    return not any(ord(character) < 32 for character in value)


def _manifest_install_directory(path: Path) -> str | None:
    """Return the app's top-level safe install directory for a supported manifest."""
    try:
        entries = _read_vdf(path)
    except (OSError, _VdfParseError, ValueError):
        return None
    app_state = _single_named_entry(entries, "AppState")
    if app_state is None or not isinstance(app_state.value, tuple):
        return None
    app_id = _single_scalar(app_state.value, "appid")
    install_directory = _single_scalar(app_state.value, "installdir")
    if app_id != APP_ID or install_directory is None:
        return None
    if not _valid_install_directory(install_directory):
        return None
    return install_directory


def _path_is_within(path: Path, directory: Path) -> bool:
    """Check resolved containment so an install-directory symlink cannot escape."""
    try:
        resolved_path = path.resolve(strict=True)
        resolved_directory = directory.resolve(strict=True)
        resolved_path.relative_to(resolved_directory)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _has_rimworld_markers(game_path: Path, common_path: Path) -> bool:
    """Require RimWorld's named executable and a known game-data directory."""
    if not game_path.is_dir() or not _path_is_within(game_path, common_path):
        return False
    has_game_executable = any(
        (game_path / filename).is_file() for filename in _KNOWN_GAME_EXECUTABLES
    )
    if not has_game_executable:
        return False
    return any(
        (game_path / directory).is_dir()
        for directory in _KNOWN_GAME_DATA_DIRECTORIES
    )


def _discover_from_roots(
    root_candidates: Iterable[str | Path],
) -> tuple[RimWorldSteamInstallation, ...]:
    """Discover validated installs from injectable Steam roots without volume scans."""
    libraries: dict[str, Path] = {}
    roots: dict[str, Path] = {}
    for candidate in root_candidates:
        try:
            root = Path(candidate)
        except (OSError, TypeError, ValueError):
            continue
        _add_unique_path(roots, root)

    for root in roots.values():
        steamapps = root / "steamapps"
        try:
            if not steamapps.is_dir():
                continue
        except (OSError, ValueError):
            continue
        _add_unique_path(libraries, root)
        libraryfolders = steamapps / "libraryfolders.vdf"
        try:
            if not libraryfolders.is_file():
                continue
            entries = _read_vdf(libraryfolders)
        except (OSError, _VdfParseError, ValueError):
            continue
        for library_path in _library_paths(entries):
            _add_unique_path(libraries, library_path)

    installations: dict[str, RimWorldSteamInstallation] = {}
    for library_key in sorted(libraries):
        library = libraries[library_key]
        steamapps = library / "steamapps"
        manifest = steamapps / f"appmanifest_{APP_ID}.acf"
        install_directory = _manifest_install_directory(manifest)
        if install_directory is None:
            continue

        common_path = steamapps / "common"
        game_path = common_path / install_directory
        if not _has_rimworld_markers(game_path, common_path):
            continue

        workshop_candidate = (
            steamapps / "workshop" / "content" / APP_ID
        )
        try:
            workshop_path = workshop_candidate if workshop_candidate.is_dir() else None
        except OSError:
            workshop_path = None
        installations[library_key] = RimWorldSteamInstallation(
            game_path=game_path,
            workshop_path=workshop_path,
        )

    return tuple(installations[key] for key in sorted(installations))


def discover_rimworld_steam_installations() -> tuple[RimWorldSteamInstallation, ...]:
    """Return all validated Steam RimWorld installs found on Windows.

    The search uses Steam registry/default roots and their library metadata; it
    never walks a drive or mod directory. Each call reads current filesystem
    state and returns no results on non-Windows platforms.
    """
    if not _is_windows():
        return ()
    return _discover_from_roots(_steam_root_candidates())
