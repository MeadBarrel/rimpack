"""Interactive setup orchestration for Rimpack's two managed settings paths."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal, Protocol, Sequence

from rimpack.cli.config_editing import (
    ConfigSnapshot,
    load_config_snapshot,
    save_config_snapshot,
    serialize_setup_settings,
)
from rimpack.sdk.config import Settings
from rimpack.sdk.diagnostics import render_diagnostics
from rimpack.sdk.installation_discovery import (
    RimWorldSteamInstallation,
    discover_rimworld_steam_installations,
)


class SetupCancelled(Exception):
    """Signal that Ctrl-C or EOF cancelled setup without saving changes."""


class SetupError(RuntimeError):
    """Describe a setup flow failure that should be reported as an operational error."""


class InvalidManualPath(ValueError):
    """Explain why raw path text cannot be used as a configured setup path."""


@dataclass(frozen=True, slots=True)
class ChoiceOption:
    """Represent one typed setup choice with a stable prompt key and label."""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class SetupWarning:
    """Identify one overridable filesystem or installation-layout concern."""

    field: Literal["rimworld_path", "workshop_path"]
    path: Path
    kind: Literal["missing", "inaccessible", "not_directory", "layout"]
    message: str

    @property
    def identity(self) -> tuple[str, str, str]:
        """Return a stable acknowledgement key for this exact field and path issue."""
        return self.field, os.path.normcase(os.path.normpath(str(self.path))), self.kind


@dataclass(frozen=True, slots=True)
class SetupOutcome:
    """Report the selected file and whether setup saved, skipped, or was declined."""

    path: Path
    status: Literal["saved", "unchanged", "declined"]


class SetupUI(Protocol):
    """Describe the narrow typed interaction surface required by the wizard."""

    def choose(
        self,
        message: str,
        options: Sequence[ChoiceOption],
        *,
        default: str,
    ) -> str:
        """Return one offered option key without exposing prompt-library values."""
        ...

    def enter_path(self, message: str) -> str:
        """Return raw path text; validation and expansion belong to setup logic."""
        ...

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """Return an explicit yes/no answer using the supplied default."""
        ...

    def show(self, message: str, *, kind: str = "info") -> None:
        """Display literal user-facing text without interpreting markup."""
        ...


def escape_terminal_controls(value: str) -> str:
    """Escape non-printable characters so user paths cannot inject terminal codes."""
    escaped: list[str] = []
    for character in value:
        if character.isprintable():
            escaped.append(character)
        elif ord(character) <= 0xFF:
            escaped.append(f"\\x{ord(character):02x}")
        elif ord(character) <= 0xFFFF:
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(f"\\U{ord(character):08x}")
    return "".join(escaped)


def resolve_manual_path(value: str, *, cwd: Path, home: Path) -> Path:
    """Validate manual text, expand only current-user tilde, and anchor it lexically.

    Meaningful spaces and environment-variable expressions are retained. The
    result is absolute without resolving symlinks; Windows drive-relative forms
    are rejected by the same ``Settings`` validation used for YAML values.
    """
    if not value or not value.strip():
        raise InvalidManualPath("enter a nonempty, non-whitespace path")
    if "\x00" in value:
        raise InvalidManualPath("paths cannot contain NUL")
    try:
        path = Path(value)
    except (OSError, TypeError, ValueError) as error:
        raise InvalidManualPath(f"invalid path text: {error}") from error
    if path.drive and not path.root:
        raise InvalidManualPath(
            "drive-relative paths are not supported; use an absolute path such as "
            "C:/game or a relative path such as game"
        )
    if path.parts and path.parts[0] == "~":
        path = home.joinpath(*path.parts[1:])
    invocation_cwd = cwd if cwd.is_absolute() else Path(os.path.abspath(cwd))
    if not path.is_absolute():
        path = invocation_cwd / path
    try:
        Settings(rimworld_path=path)
    except (OSError, TypeError, ValueError) as error:
        raise InvalidManualPath(str(error)) from error
    return path


def _path_key(path: Path) -> str:
    """Normalize lexical spellings using host case and separator rules."""
    return os.path.normcase(os.path.normpath(str(path)))


def _discover_candidates(
    ui: SetupUI,
    discover: Callable[[], tuple[RimWorldSteamInstallation, ...]],
) -> tuple[RimWorldSteamInstallation, ...]:
    """Call Steam discovery explicitly, falling back to manual choices on OS errors."""
    try:
        candidates = discover()
    except OSError as error:
        ui.show(
            "Steam installation discovery could not complete; you can enter paths "
            f"manually. {error}",
            kind="warning",
        )
        return ()
    if not candidates:
        ui.show(
            "Automatic Steam discovery returned no candidates. This does not mean "
            "RimWorld is not installed; manual path entry is available.",
            kind="warning",
        )
    return candidates


def _path_choice_label(path: Path) -> str:
    """Render one path as a safe literal prompt label."""
    return escape_terminal_controls(str(path))


def _manual_path(ui: SetupUI, message: str, *, cwd: Path, home: Path) -> Path:
    """Reprompt after invalid text while propagating cancellation immediately."""
    while True:
        raw_value = ui.enter_path(message)
        try:
            return resolve_manual_path(raw_value, cwd=cwd, home=home)
        except InvalidManualPath as error:
            ui.show(f"Invalid path: {error}", kind="error")


def _select_installation(
    ui: SetupUI,
    current: Path | None,
    candidates: tuple[RimWorldSteamInstallation, ...],
    *,
    cwd: Path,
    home: Path,
) -> Path:
    """Select a current, discovered, or manually entered required game path."""
    options: list[ChoiceOption] = []
    if current is not None:
        options.append(
            ChoiceOption("current", f"Keep current: {_path_choice_label(current)}")
        )
    for index, candidate in enumerate(candidates):
        options.append(
            ChoiceOption(
                f"discovered:{index}",
                f"Discovered: {_path_choice_label(candidate.game_path)}",
            )
        )
    options.append(ChoiceOption("manual", "Enter a path manually"))
    default = (
        "current"
        if current is not None
        else "discovered:0"
        if len(candidates) == 1
        else "manual"
    )
    selected = ui.choose(
        "Choose the RimWorld installation (required)", options, default=default
    )
    valid_keys = {option.key for option in options}
    if selected not in valid_keys:
        raise SetupError("the setup interface returned an unavailable choice")
    if selected == "manual":
        return _manual_path(
            ui,
            "RimWorld installation directory",
            cwd=cwd,
            home=home,
        )
    if selected == "current":
        assert current is not None
        return current
    candidate_index = int(selected.split(":", 1)[1])
    return candidates[candidate_index].game_path


def _matching_candidate(
    installation_path: Path,
    candidates: tuple[RimWorldSteamInstallation, ...],
) -> RimWorldSteamInstallation | None:
    """Find a discovered install matching a retained or manually entered path."""
    key = _path_key(installation_path)
    return next(
        (
            candidate
            for candidate in candidates
            if _path_key(candidate.game_path) == key
        ),
        None,
    )


def _select_workshop(
    ui: SetupUI,
    current: Path | None,
    installation: Path,
    candidates: tuple[RimWorldSteamInstallation, ...],
    *,
    cwd: Path,
    home: Path,
) -> Path | None:
    """Choose retained, associated, manual, or explicitly unconfigured Workshop."""
    associated = _matching_candidate(installation, candidates)
    suggested_workshop = associated.workshop_path if associated is not None else None
    options: list[ChoiceOption] = []
    if current is not None:
        options.append(
            ChoiceOption("current", f"Keep current: {_path_choice_label(current)}")
        )
    if suggested_workshop is not None:
        options.append(
            ChoiceOption(
                "suggested",
                "Discovered for this installation: "
                f"{_path_choice_label(suggested_workshop)}",
            )
        )
    options.extend(
        (
            ChoiceOption("manual", "Enter a Workshop path manually"),
            ChoiceOption("none", "No Workshop source"),
        )
    )
    default = (
        "current"
        if current is not None
        else "suggested"
        if suggested_workshop is not None
        else "none"
    )
    selected = ui.choose(
        "Choose the Workshop content directory", options, default=default
    )
    if selected not in {option.key for option in options}:
        raise SetupError("the setup interface returned an unavailable choice")
    if selected == "current":
        assert current is not None
        return current
    if selected == "suggested":
        assert suggested_workshop is not None
        return suggested_workshop
    if selected == "none":
        return None
    return _manual_path(
        ui,
        "Workshop content directory",
        cwd=cwd,
        home=home,
    )


def _is_regular_file(path: Path) -> bool:
    """Check one direct marker with metadata only, treating access errors as absent."""
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except OSError:
        return False


def _is_directory(path: Path) -> bool:
    """Check one direct marker directory without enumerating its contents."""
    try:
        return stat.S_ISDIR(path.stat().st_mode)
    except OSError:
        return False


def installation_layout_is_recognized(path: Path) -> bool:
    """Recognize direct Windows/Linux markers or a populated macOS app bundle."""
    from rimpack.sdk.installation_discovery import (
        _KNOWN_GAME_DATA_DIRECTORIES,
        _KNOWN_GAME_EXECUTABLES,
    )

    data_directories = (
        *_KNOWN_GAME_DATA_DIRECTORIES,
        "RimWorldLinux_Data",
        "RimWorldLinux64_Data",
    )
    has_data = any(_is_directory(path / name) for name in data_directories)
    windows_launcher = any(
        _is_regular_file(path / name) for name in _KNOWN_GAME_EXECUTABLES
    )
    linux_launcher = any(
        _is_regular_file(path / name) for name in ("RimWorldLinux", "RimWorldLinux64")
    )
    if has_data and (windows_launcher or linux_launcher):
        return True

    app = path / "RimWorldMac.app"
    mac_launcher = _is_regular_file(app / "Contents" / "MacOS" / "RimWorldMac")
    mac_data = any(
        _is_directory(app / "Contents" / "Resources" / name)
        for name in ("Data", "RimWorldMac_Data")
    )
    return mac_launcher and mac_data


def _check_directory(
    path: Path, field: Literal["rimworld_path", "workshop_path"]
) -> tuple[SetupWarning, ...]:
    """Classify one configured path without walking or listing its contents."""
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return (
            SetupWarning(
                field, path, "missing", "the configured directory does not exist"
            ),
        )
    except OSError:
        return (
            SetupWarning(field, path, "inaccessible", "the path cannot be accessed"),
        )
    if not stat.S_ISDIR(metadata.st_mode):
        return (
            SetupWarning(field, path, "not_directory", "the target is not a directory"),
        )
    try:
        with os.scandir(path):
            pass
    except FileNotFoundError:
        return (
            SetupWarning(
                field, path, "missing", "the configured directory disappeared"
            ),
        )
    except OSError:
        return (
            SetupWarning(
                field, path, "inaccessible", "the directory cannot be accessed"
            ),
        )
    if field == "rimworld_path" and not installation_layout_is_recognized(path):
        return (
            SetupWarning(
                field,
                path,
                "layout",
                "the directory does not contain a recognized RimWorld launcher "
                "and game data",
            ),
        )
    return ()


def check_setup_paths(settings: Settings) -> tuple[SetupWarning, ...]:
    """Check configured game and Workshop directories and return typed warnings."""
    warnings: list[SetupWarning] = []
    if settings.rimworld_path is not None:
        warnings.extend(_check_directory(settings.rimworld_path, "rimworld_path"))
    if settings.workshop_path is not None:
        warnings.extend(_check_directory(settings.workshop_path, "workshop_path"))
    return tuple(warnings)


def _format_settings_review(
    snapshot: ConfigSnapshot,
    current: Settings,
    proposed: Settings,
    acknowledged: Sequence[SetupWarning],
) -> str:
    """Show concise path changes and the effective sources before saving."""
    safe = escape_terminal_controls

    def shown(path: Path | None) -> str:
        """Render absent settings explicitly and configured paths safely."""
        return "unconfigured" if path is None else safe(str(path))

    lines = [
        f"Settings: {safe(str(snapshot.path))}",
        f"RimWorld: {shown(current.rimworld_path)} -> {shown(proposed.rimworld_path)}",
        f"Workshop: {shown(current.workshop_path)} -> {shown(proposed.workshop_path)}",
    ]
    data_kind = "override" if proposed.data_path is not None else "derived"
    mods_kind = "override" if proposed.mods_path is not None else "derived"
    lines.extend(
        (
            f"Data ({data_kind}): {shown(proposed.effective_data_path)}",
            f"Mods ({mods_kind}): {shown(proposed.effective_mods_path)}",
        )
    )
    if acknowledged:
        lines.append("Warnings:")
        lines.extend(
            f"  - {warning.field} ({warning.kind}): "
            f"{safe(str(warning.path))} — {warning.message}"
            for warning in acknowledged
        )
    else:
        lines.append("Warnings: none")
    return "\n".join(lines)


def _select_and_check_paths(
    ui: SetupUI,
    snapshot: ConfigSnapshot,
    candidates: tuple[RimWorldSteamInstallation, ...],
    *,
    cwd: Path,
    home: Path,
) -> tuple[Settings, tuple[SetupWarning, ...]]:
    """Select paths and return only after every current warning was acknowledged."""
    current = snapshot.result.value
    installation = _select_installation(
        ui, current.rimworld_path, candidates, cwd=cwd, home=home
    )
    workshop = _select_workshop(
        ui,
        current.workshop_path,
        installation,
        candidates,
        cwd=cwd,
        home=home,
    )
    acknowledged: dict[tuple[str, str, str], SetupWarning] = {}

    while True:
        proposed = replace(
            current,
            rimworld_path=installation,
            workshop_path=workshop,
        )
        warnings = check_setup_paths(proposed)
        unacknowledged = next(
            (warning for warning in warnings if warning.identity not in acknowledged),
            None,
        )
        if unacknowledged is None:
            return proposed, tuple(
                warning for warning in warnings if warning.identity in acknowledged
            )
        accepted = ui.confirm(
            f"Warning for {unacknowledged.field} at "
            f"{escape_terminal_controls(str(unacknowledged.path))}: "
            f"{unacknowledged.message}. Use this path anyway?",
            default=False,
        )
        if accepted:
            acknowledged[unacknowledged.identity] = unacknowledged
            continue
        if unacknowledged.field == "rimworld_path":
            installation = _select_installation(
                ui, current.rimworld_path, candidates, cwd=cwd, home=home
            )
            workshop = _select_workshop(
                ui,
                current.workshop_path,
                installation,
                candidates,
                cwd=cwd,
                home=home,
            )
        else:
            workshop = _select_workshop(
                ui,
                current.workshop_path,
                installation,
                candidates,
                cwd=cwd,
                home=home,
            )


def run_setup(
    config: str | Path | None,
    ui: SetupUI,
    *,
    discover: Callable[[], tuple[RimWorldSteamInstallation, ...]] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> SetupOutcome:
    """Run the setup wizard through an injected UI and explicit discovery boundary.

    Callers must verify that stdin and stdout are usable terminals before
    entering this function. This keeps the domain flow scriptable in tests while
    the CLI remains interactive-only.
    """
    invocation_cwd = cwd if cwd is not None else Path.cwd()
    user_home = home if home is not None else Path.home()
    snapshot = load_config_snapshot(config)
    if snapshot.result.diagnostics:
        ui.show(
            "Unknown configuration fields will be preserved:\n"
            + render_diagnostics(snapshot.result.diagnostics),
            kind="warning",
        )
    discovery = (
        discover if discover is not None else discover_rimworld_steam_installations
    )
    candidates = _discover_candidates(ui, discovery)
    proposed, acknowledged = _select_and_check_paths(
        ui,
        snapshot,
        candidates,
        cwd=invocation_cwd,
        home=user_home,
    )
    ui.show(
        _format_settings_review(
            snapshot, snapshot.result.value, proposed, acknowledged
        ),
        kind="review",
    )
    if not ui.confirm("Save these settings?", default=False):
        ui.show("Setup declined; no settings were changed.")
        return SetupOutcome(snapshot.path, "declined")

    changed = (
        snapshot.result.value.rimworld_path != proposed.rimworld_path
        or snapshot.result.value.workshop_path != proposed.workshop_path
    )
    if not changed and snapshot.source is not None:
        ui.show(
            f"Settings are unchanged at {escape_terminal_controls(str(snapshot.path))}."
        )
        return SetupOutcome(snapshot.path, "unchanged")

    serialized = serialize_setup_settings(snapshot, proposed)
    save_config_snapshot(snapshot, serialized)
    ui.show(f"Settings saved to {escape_terminal_controls(str(snapshot.path))}.")
    return SetupOutcome(snapshot.path, "saved")
