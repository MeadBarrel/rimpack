"""Interactive setup, comment-aware YAML editing, and CLI boundary tests."""

from __future__ import annotations

import os
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Sequence

import pytest
from rich.text import Text
from ruamel.yaml import YAML
from typer.testing import CliRunner

from rimpack.cli import app, config_editing, logging_config, prompts, setup
from rimpack.cli.config_editing import (
    ConcurrentConfigChange,
    load_config_snapshot,
    save_config_snapshot,
    serialize_setup_settings,
)
from rimpack.cli.setup import (
    ChoiceOption,
    SetupCancelled,
    SetupOutcome,
    check_setup_paths,
    resolve_manual_path,
    run_setup,
)
from rimpack.cli.yaml_editing import create_round_trip_yaml
from rimpack.sdk.config import ConfigParseError, Settings, parse_config_yaml
from rimpack.sdk.installation_discovery import RimWorldSteamInstallation


class ScriptedUI:
    """Supply deterministic prompt answers and retain all displayed wizard text."""

    def __init__(
        self,
        *,
        choices: Sequence[str] = (),
        paths: Sequence[str] = (),
        confirmations: Sequence[bool] = (),
    ) -> None:
        """Initialize answer queues and output capture for one wizard run."""
        self.choices = list(choices)
        self.paths = list(paths)
        self.confirmations = list(confirmations)
        self.messages: list[tuple[str, str]] = []
        self.choice_calls: list[tuple[str, tuple[ChoiceOption, ...], str]] = []
        self.confirm_calls: list[tuple[str, bool]] = []

    def choose(
        self,
        message: str,
        options: Sequence[ChoiceOption],
        *,
        default: str,
    ) -> str:
        """Return the next scripted choice after recording its available menu."""
        self.choice_calls.append((message, tuple(options), default))
        if not self.choices:
            raise AssertionError(f"no scripted choice remains for {message}")
        choice = self.choices.pop(0)
        assert choice in {option.key for option in options}
        return choice

    def enter_path(self, message: str) -> str:
        """Return the next raw path answer without normalizing its spelling."""
        if not self.paths:
            raise AssertionError(f"no scripted path remains for {message}")
        return self.paths.pop(0)

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """Return the next scripted confirmation and remember its default."""
        self.confirm_calls.append((message, default))
        if not self.confirmations:
            raise AssertionError(f"no scripted confirmation remains for {message}")
        return self.confirmations.pop(0)

    def show(self, message: str, *, kind: str = "info") -> None:
        """Capture output exactly as the terminal adapter receives it."""
        self.messages.append((kind, message))


def create_installation(path: Path) -> Path:
    """Create direct launcher and data markers for a usable fake game root."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "RimWorldWin64.exe").write_bytes(b"test executable")
    (path / "Data").mkdir(exist_ok=True)
    return path


def create_discovery(
    game: Path, workshop: Path | None = None
) -> RimWorldSteamInstallation:
    """Build one Steam discovery record with optional Workshop suggestion."""
    return RimWorldSteamInstallation(game_path=game, workshop_path=workshop)


def make_ui(
    *,
    choices: Sequence[str] = (),
    paths: Sequence[str] = (),
    confirmations: Sequence[bool] = (),
) -> ScriptedUI:
    """Construct the scripted typed prompt boundary used by setup tests."""
    return ScriptedUI(choices=choices, paths=paths, confirmations=confirmations)


def parse_candidate(source_path: Path, content: bytes) -> Settings:
    """Check generated YAML with the unchanged SDK reader beside its source file."""
    path = source_path.with_name("candidate.yml")
    path.write_bytes(content)
    return parse_config_yaml(path).value


def test_shared_round_trip_yaml_preserves_native_scalars_and_quote_styles() -> None:
    """Retain ruamel's native null, boolean, and numeric scalar semantics."""
    source = (
        "unknown:\n  '': blank key\n  null: null\n  true: true\n  2: 2\n  empty: \"\"\n"
    )
    yaml = create_round_trip_yaml(source)
    mapping = yaml.load(source)
    expected = {"": "blank key", None: None, True: True, 2: 2, "empty": ""}

    assert mapping["unknown"] == expected
    output = StringIO()
    yaml.dump(mapping, output)
    serialized = output.getvalue()

    assert "  '': blank key\n" in serialized
    assert YAML(typ="safe", pure=True).load(serialized)["unknown"] == expected


def test_manual_paths_expand_only_home_and_anchor_relative_input(
    tmp_path: Path,
) -> None:
    """Preserve spaces and variables while applying tilde and cwd rules."""
    cwd = tmp_path / "work"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()

    assert resolve_manual_path("folder with spaces", cwd=cwd, home=home) == (
        cwd / "folder with spaces"
    )
    assert resolve_manual_path("~/mods", cwd=cwd, home=home) == home / "mods"
    assert resolve_manual_path("$RIMPACK_TEST/path", cwd=cwd, home=home) == (
        cwd / "$RIMPACK_TEST" / "path"
    )
    assert resolve_manual_path("  kept spaces  ", cwd=cwd, home=home) == (
        cwd / "  kept spaces  "
    )


def test_manual_paths_reject_empty_whitespace_and_nul(tmp_path: Path) -> None:
    """Reject malformed raw values before they can become configured paths."""
    for value in ("", " \t", "bad\x00path"):
        with pytest.raises(setup.InvalidManualPath):
            resolve_manual_path(value, cwd=tmp_path, home=tmp_path)


def test_windows_drive_relative_manual_paths_are_rejected(tmp_path: Path) -> None:
    """Reject host-native per-drive working-directory syntax on Windows."""
    if os.name != "nt":
        pytest.skip("Windows drive-relative syntax")
    with pytest.raises(setup.InvalidManualPath, match="drive-relative"):
        resolve_manual_path("C:game", cwd=tmp_path, home=tmp_path)


def test_setup_creates_only_selected_missing_configuration_after_confirmation(
    tmp_path: Path,
) -> None:
    """Save an explicitly selected missing settings file without default fallback."""
    profile = tmp_path / "profiles" / "testing"
    selected = create_installation(tmp_path / "game")
    ui = make_ui(
        choices=["manual", "none"],
        paths=[str(selected)],
        confirmations=[True],
    )

    outcome = run_setup(
        profile / "settings.yml",
        ui,
        discover=lambda: (),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert outcome == SetupOutcome(profile / "settings.yml", "saved")
    assert ui.choice_calls[1][2] == "none"
    assert (
        (profile / "settings.yml")
        .read_text(encoding="utf-8")
        .startswith("rimworld_path:")
    )
    assert not (tmp_path / ".rimpack" / "settings.yml").exists()
    assert profile.exists()


def test_single_discovered_installation_needs_no_extra_confirmation(
    tmp_path: Path,
) -> None:
    """Select the sole offered candidate directly, then confirm only the final save."""
    game = create_installation(tmp_path / "game")
    workshop = tmp_path / "library" / "workshop"
    workshop.mkdir(parents=True)
    candidate = create_discovery(game, workshop)
    selected_config = tmp_path / "settings.yml"
    ui = make_ui(choices=["discovered:0", "none"], confirmations=[True])

    result = run_setup(
        selected_config,
        ui,
        discover=lambda: (candidate,),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "saved"
    assert ui.choice_calls[0][2] == "discovered:0"
    assert ui.choice_calls[1][2] == "suggested"
    assert ui.confirm_calls == [("Save these settings?", False)]
    assert "rimworld_path" in selected_config.read_text(encoding="utf-8")


def test_current_paths_remain_defaults_on_reruns_and_noop_preserves_bytes_and_mtime(
    tmp_path: Path,
) -> None:
    """Keep configured paths instead of replacing them with new discovery results."""
    create_installation(tmp_path / "game")
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    selected_config = tmp_path / "settings.yml"
    selected_config.write_text(
        "rimworld_path: game\nworkshop_path: workshop\n", encoding="utf-8"
    )
    original = selected_config.read_bytes()
    original_mtime = selected_config.stat().st_mtime_ns
    different = create_installation(tmp_path / "new-game")
    ui = make_ui(choices=["current", "current"], confirmations=[True])

    result = run_setup(
        selected_config,
        ui,
        discover=lambda: (create_discovery(different),),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "unchanged"
    assert selected_config.read_bytes() == original
    assert selected_config.stat().st_mtime_ns == original_mtime
    assert [call[2] for call in ui.choice_calls] == ["current", "current"]


def test_discovery_matches_a_manually_selected_installation_for_workshop_suggestion(
    tmp_path: Path,
) -> None:
    """Offer the matching discovered Workshop even when game entry was manual."""
    game = create_installation(tmp_path / "game")
    workshop = tmp_path / "library" / "workshop"
    workshop.mkdir(parents=True)
    candidate = create_discovery(game, workshop)
    ui = make_ui(
        choices=["manual", "suggested"],
        paths=[str(game)],
        confirmations=[True],
    )

    result = run_setup(
        tmp_path / "settings.yml",
        ui,
        discover=lambda: (candidate,),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "saved"
    assert "Discovered for this installation" in str(ui.choice_calls[1][1])
    assert ui.choice_calls[1][2] == "suggested"
    assert (
        load_config_snapshot(tmp_path / "settings.yml").result.value.workshop_path
        == workshop
    )


def test_workshop_current_value_is_not_silently_replaced_when_installation_changes(
    tmp_path: Path,
) -> None:
    """Retain the Workshop default across an explicit installation change."""
    old_game = create_installation(tmp_path / "old-game")
    new_game = create_installation(tmp_path / "new-game")
    old_workshop = tmp_path / "old-workshop"
    old_workshop.mkdir()
    selected_config = tmp_path / "settings.yml"
    selected_config.write_text(
        "rimworld_path: old-game\nworkshop_path: old-workshop\n", encoding="utf-8"
    )
    ui = make_ui(choices=["discovered:0", "current"], confirmations=[True])

    result = run_setup(
        selected_config,
        ui,
        discover=lambda: (create_discovery(new_game),),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "saved"
    loaded = load_config_snapshot(selected_config).result.value
    assert loaded.rimworld_path == new_game
    assert loaded.workshop_path == old_workshop
    assert old_game.exists()


def test_clearing_workshop_removes_only_that_field_and_reviews_derived_overrides(
    tmp_path: Path,
) -> None:
    """Show cleared Workshop and retain explicit Data/Mods and extra roots."""
    game = create_installation(tmp_path / "game")
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    (tmp_path / "custom-data").mkdir()
    (tmp_path / "custom-mods").mkdir()
    (tmp_path / "extra-mods").mkdir()
    selected_config = tmp_path / "settings.yml"
    selected_config.write_text(
        "rimworld_path: game\n"
        "workshop_path: workshop # old Workshop source\n"
        "data_path: custom-data\n"
        "mods_path: custom-mods\n"
        "extra_mod_paths:\n"
        "  - extra-mods\n",
        encoding="utf-8",
    )
    ui = make_ui(choices=["current", "none"], confirmations=[True])

    outcome = run_setup(
        selected_config,
        ui,
        discover=lambda: (),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert outcome.status == "saved"
    assert ui.choice_calls[1][2] == "current"
    saved = load_config_snapshot(selected_config).result.value
    assert saved.rimworld_path == game
    assert saved.workshop_path is None
    assert saved.data_path == tmp_path / "custom-data"
    assert saved.mods_path == tmp_path / "custom-mods"
    assert saved.extra_mod_paths == (tmp_path / "extra-mods",)
    review = next(message for kind, message in ui.messages if kind == "review")
    assert f"Workshop: {workshop} -> unconfigured" in review
    assert "Data (override):" in review
    assert "Mods (override):" in review
    output = selected_config.read_text(encoding="utf-8")
    assert "workshop_path" not in output


def test_rejecting_a_path_warning_reopens_that_field_for_selection(
    tmp_path: Path,
) -> None:
    """Require a new path choice after declining a missing-path override."""
    missing = tmp_path / "missing-game"
    valid = create_installation(tmp_path / "valid-game")
    selected_config = tmp_path / "settings.yml"
    ui = make_ui(
        choices=["manual", "none", "manual", "none"],
        paths=[str(missing), str(valid)],
        confirmations=[False, True],
    )

    result = run_setup(
        selected_config,
        ui,
        discover=lambda: (),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "saved"
    assert [call[0] for call in ui.confirm_calls] == [
        f"Warning for rimworld_path at {missing}: the configured directory "
        "does not exist. Use this path anyway?",
        "Save these settings?",
    ]
    assert "missing-game" not in selected_config.read_text(encoding="utf-8")


def test_invalid_manual_entry_is_explained_and_reprompted(tmp_path: Path) -> None:
    """Reject blank input without permitting a warning override to accept it."""
    game = create_installation(tmp_path / "valid-game")
    ui = make_ui(
        choices=["manual", "none"],
        paths=["   ", str(game)],
        confirmations=[True],
    )

    result = run_setup(
        tmp_path / "settings.yml",
        ui,
        discover=lambda: (),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "saved"
    assert any(
        kind == "error" and "Invalid path" in message for kind, message in ui.messages
    )
    assert not any("Warning for" in message for message, _ in ui.confirm_calls)


def test_discovery_filesystem_failure_warns_and_keeps_manual_entry(
    tmp_path: Path,
) -> None:
    """Fall back to manual paths after expected Steam filesystem failures."""
    game = create_installation(tmp_path / "game")
    ui = make_ui(
        choices=["manual", "none"],
        paths=[str(game)],
        confirmations=[True],
    )

    def failed_discovery() -> tuple[RimWorldSteamInstallation, ...]:
        """Model a filesystem failure while Steam candidates are inspected."""
        raise PermissionError("discovery access denied")

    result = run_setup(
        tmp_path / "settings.yml",
        ui,
        discover=failed_discovery,
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "saved"
    warning = next(message for kind, message in ui.messages if kind == "warning")
    assert "enter paths manually" in warning
    assert "not installed" not in warning


def test_layout_warning_requires_separate_default_no_acknowledgement(
    tmp_path: Path,
) -> None:
    """Allow an unusual but accessible directory only after warning acknowledgement."""
    unusual = tmp_path / "unrecognized"
    unusual.mkdir()
    ui = make_ui(
        choices=["manual", "none"],
        paths=[str(unusual)],
        confirmations=[True, True],
    )

    result = run_setup(
        tmp_path / "settings.yml",
        ui,
        discover=lambda: (),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "saved"
    assert ui.confirm_calls[0][1] is False
    assert "does not contain a recognized RimWorld launcher" in ui.confirm_calls[0][0]
    review = next(message for kind, message in ui.messages if kind == "review")
    assert "Warnings:" in review
    assert "rimworld_path (layout)" in review


def test_path_checks_distinguish_missing_non_directory_and_inaccessible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Classify three filesystem concerns without scanning directory contents."""
    missing = tmp_path / "absent"
    file_path = tmp_path / "ordinary-file"
    file_path.write_text("text", encoding="utf-8")
    inaccessible = tmp_path / "inaccessible"
    inaccessible.mkdir()
    original_scandir = os.scandir

    def blocked_scandir(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]):
        """Deny the access probe for exactly one otherwise valid directory."""
        if Path(path) == inaccessible:
            raise PermissionError("test permission denial")
        return original_scandir(path)

    monkeypatch.setattr(setup.os, "scandir", blocked_scandir)
    settings = Settings(
        rimworld_path=missing,
        workshop_path=inaccessible,
    )
    warnings = check_setup_paths(settings)
    assert [warning.kind for warning in warnings] == ["missing", "inaccessible"]
    assert (
        check_setup_paths(Settings(rimworld_path=file_path))[0].kind == "not_directory"
    )


def test_empty_accessible_workshop_directory_is_valid(tmp_path: Path) -> None:
    """Accept an empty Workshop folder without requiring subscribed mod entries."""
    game = create_installation(tmp_path / "game")
    workshop = tmp_path / "empty-workshop"
    workshop.mkdir()

    assert check_setup_paths(Settings(rimworld_path=game, workshop_path=workshop)) == ()


def test_declining_final_confirmation_does_not_create_selected_directories(
    tmp_path: Path,
) -> None:
    """Keep a missing destination path and its parent untouched after decline."""
    selected_directory = tmp_path / "not-created" / "profile"
    game = create_installation(tmp_path / "game")
    ui = make_ui(
        choices=["manual", "none"],
        paths=[str(game)],
        confirmations=[False],
    )

    result = run_setup(
        selected_directory,
        ui,
        discover=lambda: (),
        cwd=tmp_path,
        home=tmp_path,
    )

    assert result.status == "declined"
    assert not selected_directory.exists()


def test_cancelled_prompt_does_not_save_or_create_destination_parent(
    tmp_path: Path,
) -> None:
    """Propagate typed cancellation before any configuration write or mkdir."""
    target = tmp_path / "not-created" / "settings.yml"

    class CancelUI(ScriptedUI):
        """Cancel as soon as the first interactive choice is requested."""

        def choose(
            self,
            message: str,
            options: Sequence[ChoiceOption],
            *,
            default: str,
        ) -> str:
            """Raise the same cancellation marker as Ctrl-C and EOF."""
            raise SetupCancelled()

    with pytest.raises(SetupCancelled):
        run_setup(target, CancelUI(), discover=lambda: (), cwd=tmp_path, home=tmp_path)
    assert not target.parent.exists()


def test_unknown_fields_and_explicit_overrides_survive_comment_aware_edits(
    tmp_path: Path,
) -> None:
    """Retain unknown nested native values, comments, and unrelated settings."""
    selected_config = tmp_path / "settings.yml"
    original = (
        "# user configuration\n"
        "data_path: '../custom data' # explicit Data override\n"
        'mods_path: "../custom-mods"\n'
        "extra_mod_paths:\n"
        "  - >-\n"
        "    ../community\n"
        "unknown:\n"
        "  true: 00123\n"
        "  2: yes\n"
        "  date: 2024-01-02\n"
        "  unicode: 日本語とcafé\n"
        "rimworld_path: './old game'\n"
        "workshop_path: old-workshop # remove this note\n"
    )
    selected_config.write_text(original, encoding="utf-8")
    snapshot = load_config_snapshot(selected_config)
    proposed = replace(
        snapshot.result.value,
        rimworld_path=tmp_path / "new game",
        workshop_path=None,
    )

    candidate = serialize_setup_settings(snapshot, proposed)
    output = candidate.decode("utf-8-sig")

    assert parse_candidate(selected_config, candidate) == proposed
    assert "# user configuration" in output
    assert "# explicit Data override" in output
    assert "workshop_path" not in output
    assert "data_path:" in output and "mods_path:" in output
    assert "extra_mod_paths:" in output
    assert "../community" in output


def test_setup_round_trip_preserves_empty_mapping_key_and_sdk_reloads(
    tmp_path: Path,
) -> None:
    """Keep a valid empty key distinct from a literal ``null`` key after setup."""
    path = tmp_path / "settings.yml"
    path.write_text(
        "rimworld_path: old\nunknown:\n  '': blank key\n  null: null\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "new")

    candidate = serialize_setup_settings(snapshot, proposed)

    assert parse_candidate(path, candidate) == proposed
    decoded = YAML(typ="safe", pure=True).load(candidate.decode("utf-8-sig"))
    assert decoded["unknown"] == {"": "blank key", None: None}


def test_round_trip_keeps_unrelated_settings_and_comments(tmp_path: Path) -> None:
    """Preserve unrelated settings, typed scalars, and comments through ruamel."""
    path = tmp_path / "settings.yml"
    path.write_text(
        "# user configuration\n"
        "extra_mod_paths:\n"
        "- './one'  # first mod\n"
        "- >-\n"
        "    ./two\n"
        "data_path:    '../Data'   # explicit override\n"
        "unknown:\n"
        "  true: 00123\n"
        "  2: yes\n"
        "  date: 2024-01-02\n"
        "  nested:\n"
        "    - 'value'\n"
        "rimworld_path: old # keep note\n"
        "workshop_path: './kept'\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "new game")

    candidate = serialize_setup_settings(snapshot, proposed)
    output = candidate.decode("utf-8-sig")

    assert parse_candidate(path, candidate) == proposed
    original_unknown = YAML(typ="safe", pure=True).load(path.read_text())["unknown"]
    saved_unknown = YAML(typ="safe", pure=True).load(output)["unknown"]
    assert saved_unknown == original_unknown
    for preserved in (
        "# user configuration",
        "# first mod",
        "# explicit override",
        "# keep note",
        "00123",
        "2: yes",
        "2024-01-02",
        "./one",
        "./two",
        "workshop_path:",
    ):
        assert preserved in output


@pytest.mark.parametrize(
    "workshop_entry",
    [
        "workshop_path: old # removed-field note\n",
        "? workshop_path\n: old # removed-field note\n",
        "? >-\n  workshop_path\n: old\n",
    ],
)
def test_round_trip_clears_workshop_from_supported_mapping_key_forms(
    tmp_path: Path, workshop_entry: str
) -> None:
    """Let ruamel remove regular and explicit scalar mapping keys safely."""
    path = tmp_path / "settings.yml"
    path.write_text(
        "# user configuration\n"
        "rimworld_path: old\n" + workshop_entry + "mods_path: mods # keep this note\\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, workshop_path=None)

    candidate = serialize_setup_settings(snapshot, proposed)
    output = candidate.decode("utf-8-sig")

    assert parse_candidate(path, candidate) == proposed
    assert "workshop_path" not in output
    assert "# user configuration" in output
    assert "# keep this note" in output


def test_editing_an_anchored_managed_scalar_does_not_change_alias_consumers(
    tmp_path: Path,
) -> None:
    """Replace the managed alias use without mutating its anchor or other users."""
    path = tmp_path / "settings.yml"
    path.write_text(
        "shared: &shared old-game\nrimworld_path: *shared\nunknown: *shared\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "new-game")

    candidate = serialize_setup_settings(snapshot, proposed)
    mapping = create_round_trip_yaml(candidate.decode("utf-8-sig")).load(
        candidate.decode("utf-8-sig")
    )

    assert parse_candidate(path, candidate) == proposed
    assert mapping["shared"] == mapping["unknown"] == "old-game"
    assert mapping["rimworld_path"] == str(tmp_path / "new-game")


def test_editing_managed_fields_overrides_but_does_not_change_merge_sources(
    tmp_path: Path,
) -> None:
    """Write a local override while preserving inherited root settings."""
    path = tmp_path / "settings.yml"
    path.write_text(
        "defaults: &defaults {rimworld_path: old-game, workshop_path: old-workshop}\n"
        "<<: *defaults\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "new-game")

    candidate = serialize_setup_settings(snapshot, proposed)
    mapping = create_round_trip_yaml(candidate.decode("utf-8-sig")).load(
        candidate.decode("utf-8-sig")
    )

    assert parse_candidate(path, candidate) == proposed
    assert mapping["defaults"]["rimworld_path"] == "old-game"
    assert mapping["defaults"]["workshop_path"] == "old-workshop"
    assert mapping["rimworld_path"] == str(tmp_path / "new-game")
    assert mapping["workshop_path"] == "old-workshop"


@pytest.mark.parametrize(
    "source",
    [
        "defaults: &defaults {rimworld_path: game, workshop_path: inherited}\n"
        "<<: *defaults\n",
        "defaults: &defaults {rimworld_path: game, workshop_path: inherited}\n"
        "<<: *defaults\nworkshop_path: explicit\n",
    ],
)
def test_clearing_workshop_is_refused_when_a_root_merge_would_restore_it(
    tmp_path: Path, source: str
) -> None:
    """Require manual merge editing before clearing inherited Workshop paths."""
    path = tmp_path / "settings.yml"
    path.write_text(source, encoding="utf-8")
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, workshop_path=None)

    with pytest.raises(
        config_editing.ConfigEditError,
        match="root YAML merge.*remove or edit the merge manually",
    ):
        serialize_setup_settings(snapshot, proposed)


def test_block_scalar_managed_path_round_trips_as_a_path(
    tmp_path: Path,
) -> None:
    """Use the SDK to verify a changed path after ruamel rewrites its scalar style."""
    path = tmp_path / "settings.yml"
    path.write_text(
        "rimworld_path: >- # path note\n"
        "  old\n\n"
        "# next setting note\n"
        "mods_path:   mods\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "new")

    candidate = serialize_setup_settings(snapshot, proposed)
    output = candidate.decode("utf-8-sig")

    assert parse_candidate(path, candidate) == proposed
    assert "# path note" in output
    assert "# next setting note" in output
    assert "mods_path:   mods" in output or "mods_path: mods" in output


def test_adding_managed_fields_round_trips_document_markers_and_comments(
    tmp_path: Path,
) -> None:
    """Add setup fields through ruamel without dropping markers or comments."""
    path = tmp_path / "settings.yml"
    path.write_bytes(
        b"%YAML 1.2\r\n--- # start\r\n  mods_path:   mods\r\n"
        b"# end note\r\n... # end\r\n"
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "game")

    candidate = serialize_setup_settings(snapshot, proposed)
    output = candidate.decode("utf-8-sig")

    assert parse_candidate(path, candidate) == proposed
    assert "rimworld_path:" in output
    assert "# start" in output and "# end note" in output
    assert "..." in output


def test_round_trip_adds_fields_after_multiline_explicit_mapping_key(
    tmp_path: Path,
) -> None:
    """Let ruamel place new fields after an explicit scalar mapping key."""
    path = tmp_path / "settings.yml"
    path.write_text(
        "?\n  rimworld_path\n: old\nmods_path: mods\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, workshop_path=tmp_path / "workshop")

    candidate = serialize_setup_settings(snapshot, proposed)

    assert parse_candidate(path, candidate) == proposed
    assert "workshop_path:" in candidate.decode("utf-8-sig")


@pytest.mark.parametrize(
    "suffix", ["ordinary", "with'quote", "with\nnewline", "with\ttab"]
)
def test_changed_paths_are_safely_quoted_without_altering_unrelated_yaml(
    tmp_path: Path, suffix: str
) -> None:
    """Round-trip quotes and control characters through the authoritative parser."""
    path = tmp_path / "settings.yml"
    original = b"rimworld_path: old #    note\nmods_path:   mods\n"
    path.write_bytes(original)
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / suffix)

    candidate = serialize_setup_settings(snapshot, proposed)

    assert parse_candidate(path, candidate) == proposed
    output = candidate.decode("utf-8-sig")
    assert "#    note" in output
    assert "mods_path:" in output


def test_serialization_rejects_changes_to_unmanaged_settings(tmp_path: Path) -> None:
    """Refuse a proposed Settings value that would require editing other fields."""
    path = tmp_path / "settings.yml"
    path.write_bytes(b"rimworld_path: old\nmods_path: mods\n")
    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, mods_path=tmp_path / "different")

    with pytest.raises(config_editing.ConfigEditError, match="can only edit"):
        serialize_setup_settings(snapshot, proposed)


def test_setup_uses_one_sdk_load_and_does_not_revalidate_serialized_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the public SDK once, then edit captured source without more file reads."""
    path = tmp_path / "settings.yml"
    path.write_bytes(b"rimworld_path: old\n")
    original_read = Path.read_bytes
    original_parse = config_editing.parse_config_yaml
    reads: list[Path] = []
    parses: list[Path] = []

    def counted_read(source: Path) -> bytes:
        """Count byte-snapshot reads separately from the SDK's text read."""
        reads.append(source)
        return original_read(source)

    def counted_parse(source: Path):
        """Count calls to the existing public SDK loader."""
        parses.append(source)
        return original_parse(source)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    monkeypatch.setattr(config_editing, "parse_config_yaml", counted_parse)

    snapshot = load_config_snapshot(path)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "new")
    candidate = serialize_setup_settings(snapshot, proposed)

    assert candidate != snapshot.source
    assert reads == [path]
    assert parses == [path]


def test_comment_only_file_preamble_bom_and_crlf_survive_round_trip(
    tmp_path: Path,
) -> None:
    """Preserve source preamble, BOM, newline style, and explicit document markers."""
    selected_config = tmp_path / "settings.yml"
    selected_config.write_bytes(b"\xef\xbb\xbf# preamble\r\n# second line\r\n")
    snapshot = load_config_snapshot(selected_config)
    candidate = serialize_setup_settings(
        snapshot, Settings(rimworld_path=tmp_path / "game")
    )

    assert candidate.startswith(b"\xef\xbb\xbf")
    output = candidate.decode("utf-8-sig").replace("\r\n", "\n")
    assert "# preamble" in output and "# second line" in output
    assert (
        parse_candidate(selected_config, candidate).rimworld_path == tmp_path / "game"
    )


def test_workshop_deletion_keeps_document_end_marker(tmp_path: Path) -> None:
    """Delete the managed key and retain a valid explicitly ended document."""
    selected_config = tmp_path / "settings.yml"
    selected_config.write_text(
        "%YAML 1.2\n---\n"
        "rimworld_path: old\n"
        "workshop_path: old-workshop # workshop note\n"
        "...\n",
        encoding="utf-8",
    )
    snapshot = load_config_snapshot(selected_config)
    candidate = serialize_setup_settings(
        snapshot,
        replace(
            snapshot.result.value, rimworld_path=tmp_path / "new", workshop_path=None
        ),
    )
    output = candidate.decode("utf-8")

    assert "workshop_path" not in output
    assert "..." in output
    assert parse_candidate(selected_config, candidate).rimworld_path == tmp_path / "new"


def test_missing_existing_managed_key_is_appended_without_reordering_content(
    tmp_path: Path,
) -> None:
    """Append the required installation after unrelated keys without reordering."""
    selected_config = tmp_path / "settings.yml"
    selected_config.write_text("legacy: value\nworkshop_path: old\n", encoding="utf-8")
    snapshot = load_config_snapshot(selected_config)
    candidate = serialize_setup_settings(
        snapshot, replace(snapshot.result.value, rimworld_path=tmp_path / "game")
    )
    output = candidate.decode("utf-8")

    assert output.index("legacy:") < output.index("workshop_path:")
    assert output.index("workshop_path:") < output.index("rimworld_path:")


def test_setup_rejects_invalid_configuration_and_preserves_source(
    tmp_path: Path,
) -> None:
    """Do not interpret malformed recognized settings as an absent file."""
    selected_config = tmp_path / "settings.yml"
    selected_config.write_text("rimworld_path: ''\n", encoding="utf-8")
    original = selected_config.read_bytes()

    with pytest.raises(ConfigParseError):
        load_config_snapshot(selected_config)
    assert selected_config.read_bytes() == original


def test_snapshot_accepts_explicit_absence_but_distinguishes_empty_file(
    tmp_path: Path,
) -> None:
    """Use None for absence while preserving an existing zero-byte file snapshot."""
    absent = tmp_path / "absent.yml"
    absent_snapshot = load_config_snapshot(absent)
    empty = tmp_path / "empty.yml"
    empty.write_bytes(b"")
    empty_snapshot = load_config_snapshot(empty)

    assert absent_snapshot.source is None
    assert empty_snapshot.source == b""
    assert absent_snapshot.result.value == empty_snapshot.result.value == Settings()


def test_concurrent_changes_are_refused_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detect changed source bytes before the direct write can run."""
    selected_config = tmp_path / "settings.yml"
    selected_config.write_text("rimworld_path: old\n", encoding="utf-8")
    snapshot = load_config_snapshot(selected_config)
    original = b"rimworld_path: concurrently changed\n"
    selected_config.write_bytes(original)
    original_write = Path.write_bytes

    def forbidden_write(path: Path, content: bytes) -> int:
        """Fail if saving attempts a write to the concurrently edited file."""
        if path == selected_config:
            raise AssertionError("save must detect the edit before writing")
        return original_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", forbidden_write)
    with pytest.raises(ConcurrentConfigChange):
        save_config_snapshot(snapshot, b"rimworld_path: replacement\n")
    assert selected_config.read_bytes() == original


def test_new_file_after_absent_snapshot_is_not_overwritten(tmp_path: Path) -> None:
    """Refuse to overwrite a file that appeared while setup was prompting."""
    path = tmp_path / "settings.yml"
    snapshot = load_config_snapshot(path)
    concurrent = b"rimworld_path: other writer\n"
    path.write_bytes(concurrent)

    with pytest.raises(ConcurrentConfigChange, match="created"):
        save_config_snapshot(snapshot, b"rimworld_path: replacement\n")
    assert path.read_bytes() == concurrent


def test_direct_save_creates_parent_only_when_needed_and_leaves_no_artifact(
    tmp_path: Path,
) -> None:
    """Write bytes directly after confirmation, creating only needed directories."""
    path = tmp_path / "profile" / "nested" / "settings.yml"
    snapshot = load_config_snapshot(path)
    content = b"raw serialized bytes\x00\xff"

    assert not path.parent.exists()
    assert not path.parents[1].exists()
    save_config_snapshot(snapshot, content)

    assert path.read_bytes() == content
    assert set(path.parent.iterdir()) == {path}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission bits")
def test_direct_save_preserves_existing_file_permissions(tmp_path: Path) -> None:
    """Write through the existing file so its permission bits remain intact."""
    path = tmp_path / "settings.yml"
    path.write_bytes(b"before")
    path.chmod(0o640)
    snapshot = load_config_snapshot(path)

    save_config_snapshot(snapshot, b"after")

    assert path.read_bytes() == b"after"
    assert os.stat(path).st_mode & 0o777 == 0o640


def test_changes_during_snapshot_read_are_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate captured bytes without accepting a file changed during that read."""
    path = tmp_path / "settings.yml"
    path.write_bytes(b"rimworld_path: old\n")
    original_read = Path.read_bytes
    concurrent = b"rimworld_path: concurrent writer\n"

    def changed_read(source: Path) -> bytes:
        """Return old bytes after simulating a competing write to their source."""
        content = original_read(source)
        if source == path:
            path.write_bytes(concurrent)
        return content

    monkeypatch.setattr(Path, "read_bytes", changed_read)
    with pytest.raises(ConcurrentConfigChange):
        load_config_snapshot(path)
    assert original_read(path) == concurrent


def test_failed_cli_save_reports_error_and_can_leave_partial_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface a failed in-place write even when it has truncated the file."""
    import rimpack.cli as cli

    path = tmp_path / "settings.yml"
    path.write_text("rimworld_path: old\n", encoding="utf-8")
    game = create_installation(tmp_path / "game")
    ui = make_ui(choices=["manual", "none"], paths=[str(game)], confirmations=[True])
    original_write = Path.write_bytes
    partial = b"rimworld"

    def fail_after_partial_write(target: Path, content: bytes) -> int:
        """Write a deterministic prefix, then simulate a filesystem failure."""
        if target == path:
            with target.open("wb") as stream:
                stream.write(content[: len(partial)])
            raise OSError("injected write failure")
        return original_write(target, content)

    def run_setup_with_scripted_ui(
        config: str | Path | None, ignored_ui: object
    ) -> SetupOutcome:
        """Run the actual wizard with scripted responses through the CLI boundary."""
        return setup.run_setup(
            config,
            ui,
            discover=lambda: (),
            cwd=tmp_path,
            home=tmp_path,
        )

    monkeypatch.setattr(Path, "write_bytes", fail_after_partial_write)
    monkeypatch.setattr(
        logging_config,
        "managed_log_path",
        lambda: tmp_path / ".rimpack" / "logs" / "rimpack.log",
    )
    monkeypatch.setattr(cli, "terminal_is_usable", lambda: True)
    monkeypatch.setattr(cli, "PromptToolkitUI", lambda: ui)
    monkeypatch.setattr(cli, "run_setup", run_setup_with_scripted_ui)

    result = CliRunner().invoke(app, ["--config", str(path), "setup"])

    assert result.exit_code == 1
    assert any(
        kind == "error" and "Setup failed: injected write failure" in message
        for kind, message in ui.messages
    )
    assert path.read_bytes() == partial


def test_symlink_settings_file_keeps_link_and_replaces_its_target(
    tmp_path: Path,
) -> None:
    """Write through a selected file symlink without replacing the symlink itself."""
    target = tmp_path / "target.yml"
    target.write_text("rimworld_path: old\n", encoding="utf-8")
    link = tmp_path / "settings.yml"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlinks are unavailable: {error}")
    snapshot = load_config_snapshot(link)
    proposed = replace(snapshot.result.value, rimworld_path=tmp_path / "new")
    candidate = serialize_setup_settings(snapshot, proposed)

    save_config_snapshot(snapshot, candidate)

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8").find(str(tmp_path / "new")) >= 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink and parent semantics")
def test_setup_preserves_symlink_parent_path_for_snapshot_and_save(
    tmp_path: Path,
) -> None:
    """Load and replace the same file when the selected path crosses a symlink."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    other = tmp_path / "other"
    (other / "child").mkdir(parents=True)
    selected_file = other / "settings.yml"
    selected_bytes = b"rimworld_path: /game-b\n"
    selected_file.write_bytes(selected_bytes)

    normalized_file = profiles / "settings.yml"
    unrelated_bytes = b"rimworld_path: /game-a\n"
    normalized_file.write_bytes(unrelated_bytes)
    link = profiles / "link"
    try:
        link.symlink_to(other / "child", target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlinks are unavailable: {error}")
    config_path = link / ".." / "settings.yml"

    snapshot = load_config_snapshot(config_path)
    assert snapshot.path == config_path
    assert snapshot.source == selected_bytes
    assert snapshot.result.value.rimworld_path == Path("/game-b")

    proposed = replace(snapshot.result.value, rimworld_path=Path("/game-new"))
    candidate = serialize_setup_settings(snapshot, proposed)
    save_config_snapshot(snapshot, candidate)

    assert parse_config_yaml(selected_file).value.rimworld_path == Path("/game-new")
    assert normalized_file.read_bytes() == unrelated_bytes
    assert set(other.iterdir()) == {other / "child", selected_file}


def test_cli_global_config_placement_and_help_do_not_load_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep config global, reject command-local placement, and leave help inert."""
    runner = CliRunner()
    result = runner.invoke(
        app, ["--config", "profile/settings.yaml", "setup", "--help"]
    )
    assert result.exit_code == 0
    assert "--config" not in result.output

    bad_placement = runner.invoke(app, ["setup", "--config", "profile/settings.yaml"])
    assert bad_placement.exit_code == 2

    def forbidden_terminal_check() -> bool:
        """Detect if help accidentally begins interactive setup."""
        raise AssertionError("help must not inspect terminal state")

    monkeypatch.setattr("rimpack.cli.terminal_is_usable", forbidden_terminal_check)
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["setup", "--help"]).exit_code == 0


def test_cli_passes_config_text_to_sdk_without_path_coercion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass a global path argument unchanged to the setup selector boundary."""
    captured: list[str | None] = []

    def fake_setup(config: str | Path | None, ui: object) -> SetupOutcome:
        """Capture the original string and avoid touching configuration or prompts."""
        captured.append(config if isinstance(config, str) else None)
        return SetupOutcome(Path("selected"), "unchanged")

    monkeypatch.setattr(
        logging_config,
        "managed_log_path",
        lambda: tmp_path / ".rimpack" / "logs" / "rimpack.log",
    )
    monkeypatch.setattr("rimpack.cli.terminal_is_usable", lambda: True)
    monkeypatch.setattr("rimpack.cli.run_setup", fake_setup)
    result = CliRunner().invoke(app, ["--config", "not-yet-created.yaml", "setup"])

    assert result.exit_code == 0
    assert captured == ["not-yet-created.yaml"]


def test_rich_output_preserves_layout_newlines_and_escapes_inline_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render summary lines as lines while escaping terminal controls in content."""
    captured: list[str] = []

    class RecordingConsole:
        """Capture literal Rich text without writing to a terminal."""

        def __init__(self, **kwargs: object) -> None:
            """Accept the production console configuration without side effects."""

        def print(self, value: object, *, style: str | None = None) -> None:
            """Record the rendered text value for exact newline assertions."""
            captured.append(str(value))

    monkeypatch.setattr(prompts, "Console", RecordingConsole)
    prompts.PromptToolkitUI().show("Settings file: path\n\nWorkshop: bad\x1b[31m")

    assert captured == ["Settings file: path\n\nWorkshop: bad\\x1b[31m"]


def test_prompt_question_is_styled_and_required_suffix_is_deemphasized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the prompt visually prominent and its required marker subdued."""
    captured: list[object] = []

    def fake_choice(message: object, **kwargs: object) -> str:
        """Capture formatted prompt text without starting a terminal session."""
        captured.append(message)
        return "discovered:0"

    monkeypatch.setattr(prompts, "choice", fake_choice)
    selected = prompts.prompt_choice(
        "Choose the RimWorld installation (required)",
        (setup.ChoiceOption("discovered:0", "Discovered"),),
        default="discovered:0",
    )

    assert selected == "discovered:0"
    assert captured == [
        [
            ("bold fg:ansicyan", "Choose the RimWorld installation"),
            ("fg:ansibrightblack", " (required)"),
        ]
    ]


def test_review_rich_output_colors_labels_values_and_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distinguish field labels, old/new values, and their transition visually."""
    captured: list[Text] = []

    class RecordingConsole:
        """Capture styled Rich text without writing to a terminal."""

        def __init__(self, **kwargs: object) -> None:
            """Accept production console options without side effects."""

        def print(self, value: object, *, style: str | None = None) -> None:
            """Retain the styled Text instance for inspecting its spans."""
            assert isinstance(value, Text)
            captured.append(value)

    monkeypatch.setattr(prompts, "Console", RecordingConsole)
    prompts.PromptToolkitUI().show(
        "Settings: C:/settings.yml\nRimWorld: unconfigured -> E:/RimWorld",
        kind="review",
    )

    rendered = captured[0]
    value = str(rendered)
    styles = [
        (str(span.style), value[span.start : span.end]) for span in rendered.spans
    ]
    assert value == ("Settings: C:/settings.yml\nRimWorld: unconfigured -> E:/RimWorld")
    assert any("bold cyan" in style and "RimWorld:" in text for style, text in styles)
    assert any("green" in style and "unconfigured" in text for style, text in styles)
    assert any("dim" in style and " -> " in text for style, text in styles)
    assert any("green" in style and "E:/RimWorld" in text for style, text in styles)


def test_nonterminal_cli_invocation_fails_before_discovery_or_file_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report actionable noninteractive guidance before loading or creating files."""
    target = tmp_path / "missing" / "settings.yml"

    def forbidden_setup(*args: object, **kwargs: object) -> None:
        """Fail if terminal rejection reaches the setup or discovery layer."""
        raise AssertionError("nonterminal invocation must stop before setup")

    monkeypatch.setattr(
        logging_config,
        "managed_log_path",
        lambda: tmp_path / ".rimpack" / "logs" / "rimpack.log",
    )
    monkeypatch.setattr("rimpack.cli.terminal_is_usable", lambda: False)
    monkeypatch.setattr("rimpack.cli.run_setup", forbidden_setup)
    result = CliRunner().invoke(app, ["--config", str(target), "setup"])

    assert result.exit_code == 1
    assert "rimpack setup` in a" in result.output
    assert "terminal" in result.output
    assert not target.parent.exists()


def test_blank_source_normalizes_only_unsafe_blank_indentation_and_tabs(
    tmp_path: Path,
) -> None:
    """Keep comment bodies and line endings while creating fields from blank input."""
    source = b"\xef\xbb\xbf\t# first\tbody\r\n \t# second\tbody"
    path = tmp_path / "settings.yml"
    path.write_bytes(source)
    snapshot = load_config_snapshot(path)
    output = serialize_setup_settings(
        snapshot, Settings(rimworld_path=tmp_path / "game")
    )

    assert output.startswith(b"\xef\xbb\xbf # first\tbody\r\n  # second\tbody\r\n")
    assert parse_candidate(path, output).rimworld_path == tmp_path / "game"


@pytest.mark.parametrize(
    ("source", "expected_preamble"),
    [
        (b"\t \r\n\t\n", b"  \r\n \n"),
        (
            b"\xef\xbb\xbf\t# first\tbody\r\n # second\tbody\n\n# third",
            b" # first\tbody\r\n # second\tbody\n\n# third\r\n",
        ),
        (
            b"# first\tbody\n\t# second\tbody",
            b"# first\tbody\n # second\tbody\n",
        ),
    ],
)
def test_setup_saves_sdk_valid_blank_and_comment_only_sources(
    tmp_path: Path, source: bytes, expected_preamble: bytes
) -> None:
    """Save tab-indented SDK-valid empty settings without ruamel parsing tabs."""
    game = create_installation(tmp_path / "game")
    config_path = tmp_path / "settings.yml"
    config_path.write_bytes(source)
    ui = make_ui(choices=["manual", "none"], paths=[str(game)], confirmations=[True])

    result = run_setup(
        config_path, ui, discover=lambda: (), cwd=tmp_path, home=tmp_path
    )

    assert result.status == "saved"
    output = config_path.read_bytes()
    bom = b"\xef\xbb\xbf" if source.startswith(b"\xef\xbb\xbf") else b""
    assert output.startswith(bom + expected_preamble + b"rimworld_path:")
    assert parse_config_yaml(config_path).value == Settings(rimworld_path=game)
    if b"# first\tbody" in source:
        assert output.count(b"# first\tbody") == 1
        assert output.count(b"# second\tbody") == 1
        assert output.index(b"# first\tbody") < output.index(b"# second\tbody")


@pytest.mark.parametrize("cancel", [False, True])
def test_declined_or_cancelled_blank_source_remains_byte_identical(
    tmp_path: Path, cancel: bool
) -> None:
    """Leave blank bytes unchanged when the user declines or cancels the save."""
    game = create_installation(tmp_path / "game")
    config_path = tmp_path / "profile" / "settings.yml"
    config_path.parent.mkdir()
    original = b"\xef\xbb\xbf\t# keep\tthis comment\r\n\t \r\n"
    config_path.write_bytes(original)

    if cancel:

        class CancelAtConfirmation(ScriptedUI):
            """Raise cancellation on the final save question."""

            def confirm(self, message: str, *, default: bool = False) -> bool:
                """Cancel rather than returning a save decision."""
                raise SetupCancelled()

        ui = CancelAtConfirmation(choices=["manual", "none"], paths=[str(game)])
        with pytest.raises(SetupCancelled):
            run_setup(config_path, ui, discover=lambda: (), cwd=tmp_path, home=tmp_path)
    else:
        ui = make_ui(
            choices=["manual", "none"],
            paths=[str(game)],
            confirmations=[False],
        )
        assert (
            run_setup(
                config_path, ui, discover=lambda: (), cwd=tmp_path, home=tmp_path
            ).status
            == "declined"
        )

    assert config_path.read_bytes() == original
    assert list(tmp_path.rglob("*.tmp")) == []


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_blank_source_preserves_sdk_supported_unicode_line_separators(
    tmp_path: Path, separator: str
) -> None:
    """Keep uncommon but SDK-valid source separators in blank-file preambles."""
    source = f"# first\tbody{separator}\t# second\tbody".encode("utf-8")
    path = tmp_path / "settings.yml"
    path.write_bytes(source)
    snapshot = load_config_snapshot(path)
    content = serialize_setup_settings(
        snapshot, Settings(rimworld_path=tmp_path / "game")
    )
    expected = f"# first\tbody{separator} # second\tbody{separator}".encode("utf-8")

    assert content.startswith(expected)
    assert parse_candidate(path, content).rimworld_path == tmp_path / "game"


def test_setup_path_changes_keep_inline_and_standalone_document_tail(
    tmp_path: Path,
) -> None:
    """Retain comments attached to and following an end marker byte-for-byte."""
    game = create_installation(tmp_path / "new-game")
    config_path = tmp_path / "settings.yml"
    tail = b"... # retained\tinline comment\r\n# after marker\r\n  \r\n"
    config_path.write_bytes(
        b"\xef\xbb\xbfrimworld_path: old\r\nworkshop_path: old-workshop\r\n" + tail
    )
    ui = make_ui(choices=["manual", "none"], paths=[str(game)], confirmations=[True])

    result = run_setup(
        config_path, ui, discover=lambda: (), cwd=tmp_path, home=tmp_path
    )

    output = config_path.read_bytes()
    assert result.status == "saved"
    assert output.endswith(tail)
    assert output.count(b"... # retained\tinline comment") == 1
    assert output.count(b"# after marker") == 1
    assert parse_config_yaml(config_path).value == Settings(rimworld_path=game)


def test_no_change_setup_preserves_preamble_and_document_tail_bytes(
    tmp_path: Path,
) -> None:
    """Avoid rewriting unchanged settings with both a header and an end tail."""
    create_installation(tmp_path / "game")
    config_path = tmp_path / "settings.yml"
    original = (
        b"\xef\xbb\xbf# user preamble\r\n"
        b"rimworld_path: game\r\n"
        b"... # exact end\r\n"
        b"# after end\r\n"
    )
    config_path.write_bytes(original)
    ui = make_ui(choices=["current", "none"], confirmations=[True])

    result = run_setup(
        config_path, ui, discover=lambda: (), cwd=tmp_path, home=tmp_path
    )

    assert result.status == "unchanged"
    assert config_path.read_bytes() == original


def test_cli_help_is_inert_and_global_config_must_precede_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep help independent of terminal checks and command-local config options."""
    runner = CliRunner()
    assert (
        runner.invoke(
            app, ["--config", "profile/settings.yaml", "setup", "--help"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["setup", "--config", "profile/settings.yaml"]).exit_code
        == 2
    )

    def forbidden_terminal_check() -> bool:
        """Detect help that accidentally starts interactive setup."""
        raise AssertionError("help must not inspect terminal state")

    monkeypatch.setattr("rimpack.cli.terminal_is_usable", forbidden_terminal_check)
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["setup", "--help"]).exit_code == 0


def test_cli_nonterminal_invocation_fails_before_creating_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report manual configuration guidance without entering setup in a pipe."""
    target = tmp_path / "missing" / "settings.yml"
    monkeypatch.setattr(
        logging_config,
        "managed_log_path",
        lambda: tmp_path / ".rimpack" / "logs" / "rimpack.log",
    )
    monkeypatch.setattr("rimpack.cli.terminal_is_usable", lambda: False)
    result = CliRunner().invoke(app, ["--config", str(target), "setup"])

    assert result.exit_code == 1
    assert "terminal" in result.output
    assert not target.parent.exists()
