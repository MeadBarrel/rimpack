"""Setup-specific policy over shared YAML and regular-file editing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from ruamel.yaml.comments import CommentedMap

from rimpack.cli.file_editing import (
    ConcurrentFileChange,
    FileSnapshot,
    capture_file_snapshot,
    check_file_snapshot_current,
    check_file_snapshot_identity,
)
from rimpack.cli.yaml_editing import (
    YamlEditError,
    create_yaml_document,
    dump_yaml_document,
    load_yaml_document,
    string_scalar,
)
from rimpack.sdk.config import (
    ConfigLoadResult,
    Settings,
    parse_config_yaml,
    select_config_path,
)


class ConcurrentConfigChange(RuntimeError):
    """Report an observed change to the selected file after setup read it."""


class ConfigEditError(ValueError):
    """Describe a failed or semantically unsafe setup configuration edit."""


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Keep SDK-validated settings and the generic file snapshot for saving."""

    file: FileSnapshot
    result: ConfigLoadResult

    @property
    def path(self) -> Path:
        """Return the selected absolute settings-file path."""
        return self.file.path

    @property
    def source(self) -> bytes | None:
        """Return the original bytes, distinguishing absence from an empty file."""
        return self.file.original


def _root_merge_supplies(mapping: CommentedMap, key: str) -> bool:
    """Return whether a retained root merge would provide ``key`` after edits."""
    return any(key in source for source in (mapping.merge or ()))


def _raise_concurrent_config_change(error: ConcurrentFileChange) -> NoReturn:
    """Translate a generic filesystem race into the established config exception."""
    raise ConcurrentConfigChange(str(error)) from error


def _blank_or_comment_only(source: str) -> bool:
    """Match the SDK's exact blank/comment-only document predicate."""
    return all(
        not line.strip() or line.lstrip(" \t").startswith("#")
        for line in source.splitlines()
    )


def _split_line_ending(line: str) -> tuple[str, str]:
    """Separate a source line's content while retaining its exact line ending."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\r", "\n", "\x85", "\u2028", "\u2029")):
        return line[:-1], line[-1:]
    return line, ""


def _blank_document_preamble(source: str) -> str:
    """Make SDK-valid blank source safe before appending a root mapping.

    Whitespace-only line contents become ASCII spaces, and only leading tabs on
    comment lines are replaced. Tabs inside comment bodies, source ordering, and
    each existing line ending remain unchanged.
    """
    normalized: list[str] = []
    for line in source.splitlines(keepends=True):
        content, ending = _split_line_ending(line)
        if not content.strip():
            content = " " * len(content)
        elif content.lstrip(" \t").startswith("#"):
            indentation_length = len(content) - len(content.lstrip(" \t"))
            indentation = content[:indentation_length].replace("\t", " ")
            content = indentation + content[indentation_length:]
        normalized.append(content + ending)
    return "".join(normalized)


def load_config_snapshot(config: str | Path | None = None) -> ConfigSnapshot:
    """Select, capture, and SDK-load settings once before setup begins."""
    path = select_config_path(config)
    try:
        file = capture_file_snapshot(path)
    except ConcurrentFileChange as error:
        _raise_concurrent_config_change(error)

    if file.original is None:
        result = ConfigLoadResult(Settings(), path)
    else:
        result = parse_config_yaml(path)

    try:
        # Do not read content again here: the SDK parse is bracketed by identity
        # checks while the one captured byte string remains the save baseline.
        check_file_snapshot_identity(file)
    except ConcurrentFileChange as error:
        _raise_concurrent_config_change(error)
    return ConfigSnapshot(file=file, result=result)


def serialize_setup_settings(snapshot: ConfigSnapshot, proposed: Settings) -> bytes:
    """Edit only setup-managed fields in an SDK-validated native YAML mapping.

    Blank and comment-only files are special-cased using the SDK's own predicate:
    their bytes are not sent to ruamel, whose YAML indentation rules reject tabs
    that the SDK intentionally accepts for empty settings. Other source is loaded
    normally and must already be a mapping. The SDK remains the sole authority
    for input validation; serialized candidate output is not revalidated here.
    """
    if proposed.rimworld_path is None:
        raise ConfigEditError("setup cannot save without a RimWorld installation")
    if any(
        getattr(proposed, field) != getattr(snapshot.result.value, field)
        for field in ("data_path", "mods_path", "extra_mod_paths")
    ):
        raise ConfigEditError("setup can only edit installation and Workshop paths")

    if snapshot.source is None:
        source_text = ""
    else:
        try:
            source_text = snapshot.source.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ConfigEditError("settings source is not valid UTF-8") from error

    preamble = ""
    try:
        if _blank_or_comment_only(source_text):
            mapping = CommentedMap()
            document = create_yaml_document(snapshot.source, mapping)
            preamble = _blank_document_preamble(source_text)
        else:
            document = load_yaml_document(snapshot.source)
            mapping = document.root
    except YamlEditError as error:
        raise ConfigEditError(str(error)) from error

    if not isinstance(mapping, CommentedMap):
        raise ConfigEditError("the SDK-validated settings document is not a mapping")

    current = snapshot.result.value
    for field in ("rimworld_path", "workshop_path"):
        desired = getattr(proposed, field)
        if desired == getattr(current, field):
            continue
        if desired is None:
            if field != "workshop_path":
                raise ConfigEditError("setup cannot clear the installation path")
            # Deleting this key cannot clear a value inherited from a merge;
            # leave the merge source untouched rather than flattening or editing it.
            if _root_merge_supplies(mapping, field):
                raise ConfigEditError(
                    "cannot clear workshop_path because a root YAML merge would "
                    "supply it again; remove or edit the merge manually first"
                )
            mapping.pop(field, None)
        else:
            # Replace an anchored scalar instead of mutating it, so unrelated
            # alias consumers keep their original value.
            mapping[field] = string_scalar(str(desired), mapping.get(field))

    try:
        return dump_yaml_document(document, mapping, preamble=preamble)
    except YamlEditError as error:
        raise ConfigEditError(str(error)) from error


def save_config_snapshot(snapshot: ConfigSnapshot, content: bytes) -> None:
    """Write serialized bytes after checking the captured file snapshot.

    Parent directories are created only after the initial validation and once a
    save is explicitly requested. The final validation is a best-effort race
    detector, not a lock; writing in place can leave partial content on failure.
    """
    try:
        destination = snapshot.file.target_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        check_file_snapshot_current(snapshot.file)
        # In-place writes avoid staging artifacts but may leave partial content
        # if writing fails or is interrupted.
        destination.write_bytes(content)
    except ConcurrentFileChange as error:
        _raise_concurrent_config_change(error)


__all__ = [
    "ConcurrentConfigChange",
    "ConfigEditError",
    "ConfigSnapshot",
    "load_config_snapshot",
    "save_config_snapshot",
    "serialize_setup_settings",
]
