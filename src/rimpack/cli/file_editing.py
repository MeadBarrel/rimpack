"""Shared best-effort snapshot and atomic replacement helpers for regular files."""

from __future__ import annotations

import errno
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

FileIdentity = tuple[int, int, int, int, int]
DirectoryIdentity = tuple[int, int, int]


class ConcurrentFileChange(RuntimeError):
    """Report an observed file, symlink, or parent-directory change."""


@dataclass(frozen=True, slots=True)
class ParentDirectoryIdentity:
    """Identify one existing lexical parent and the directory it resolved to."""

    path: Path
    resolved_path: Path
    identity: DirectoryIdentity


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """Capture file bytes and filesystem identities without domain-specific data.

    ``original`` is ``None`` only when the selected file was genuinely absent;
    an existing empty file is represented by ``b""``. The selected path spelling
    is kept separate from ``target_path`` so saves through a file symlink replace
    its target while leaving the link itself intact.
    """

    path: Path
    original: bytes | None
    target_path: Path
    file_identity: FileIdentity | None
    target_identity: FileIdentity | None
    symlink_target: str | None
    parent_identities: tuple[ParentDirectoryIdentity, ...]


def _identity(path: Path) -> FileIdentity:
    """Return identity and change indicators without following a symlink."""
    metadata = path.lstat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _directory_identity(path: Path) -> DirectoryIdentity:
    """Return stable identity components for a resolved directory."""
    metadata = path.stat()
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _is_link_or_junction(path: Path, metadata: os.stat_result) -> bool:
    """Recognize links that must not be mistaken for genuine absence."""
    if stat.S_ISLNK(metadata.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if is_junction is not None else False


def _genuinely_absent(path: Path) -> bool:
    """Distinguish a missing entry from dangling links or invalid ancestors."""
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if candidate == path:
            return False
        if _is_link_or_junction(candidate, metadata):
            # A present but dangling link/junction makes absence ambiguous and
            # should preserve the filesystem error rather than imply a new file.
            candidate.stat()
        elif not stat.S_ISDIR(metadata.st_mode):
            raise NotADirectoryError(
                errno.ENOTDIR, "a parent path component is not a directory", candidate
            )
        return True
    return True


def _missing(path: Path) -> bool:
    """Return true only for genuine absence and let broken links fail loudly."""
    try:
        path.stat()
    except FileNotFoundError:
        return _genuinely_absent(path)
    return False


def _capture_parent_identities(path: Path) -> tuple[ParentDirectoryIdentity, ...]:
    """Capture every currently existing directory above the selected file."""
    captured: list[ParentDirectoryIdentity] = []
    for parent in path.parents:
        try:
            resolved = parent.resolve(strict=True)
            metadata = resolved.stat()
        except FileNotFoundError:
            # Continue upward: a missing selected parent may still sit beneath a
            # stable existing ancestor that can be checked during the save.
            if not _genuinely_absent(parent):
                raise
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise NotADirectoryError(
                errno.ENOTDIR, "a parent path component is not a directory", parent
            )
        captured.append(
            ParentDirectoryIdentity(
                path=parent,
                resolved_path=resolved,
                identity=(metadata.st_dev, metadata.st_ino, metadata.st_mode),
            )
        )
    return tuple(captured)


def _read_regular_file(path: Path) -> bytes:
    """Read a regular file only after rejecting directories and special nodes."""
    if not stat.S_ISREG(path.stat().st_mode):
        raise OSError(errno.EINVAL, "target must be a regular file", path)
    return path.read_bytes()


def capture_file_snapshot(path: Path) -> FileSnapshot:
    """Capture a selected absolute file path, its bytes, and best-effort identity.

    Relative paths are anchored to the current working directory by prefixing
    it, while existing absolute spellings are kept intact. In particular, ``..``
    is not collapsed before the OS follows symlinks. This helper does not expand
    tildes, select defaults, infer suffixes, or create anything. Directories,
    special files, dangling links, and invalid parent components are rejected. A
    missing target is distinct from an existing zero-byte file.
    """
    selected = path if path.is_absolute() else Path.cwd() / path
    parent_identities = _capture_parent_identities(selected)
    if _missing(selected):
        snapshot = FileSnapshot(
            path=selected,
            original=None,
            target_path=selected,
            file_identity=None,
            target_identity=None,
            symlink_target=None,
            parent_identities=parent_identities,
        )
        check_file_snapshot_identity(snapshot)
        return snapshot

    file_identity = _identity(selected)
    link_target = os.readlink(selected) if selected.is_symlink() else None
    target = selected.resolve(strict=True) if link_target is not None else selected
    target_identity = _identity(target)
    original = _read_regular_file(selected)
    snapshot = FileSnapshot(
        path=selected,
        original=original,
        target_path=target,
        file_identity=file_identity,
        target_identity=target_identity,
        symlink_target=link_target,
        parent_identities=parent_identities,
    )
    check_file_snapshot_identity(snapshot)
    return snapshot


def _check_parent_identities(snapshot: FileSnapshot) -> None:
    """Reject replaced, removed, or retargeted parents captured at read time."""
    for parent in snapshot.parent_identities:
        try:
            current_resolved = parent.path.resolve(strict=True)
            current_identity = _directory_identity(current_resolved)
        except OSError as error:
            raise ConcurrentFileChange(
                f"parent directory changed while editing: {parent.path}"
            ) from error
        if (
            current_resolved != parent.resolved_path
            or current_identity != parent.identity
        ):
            raise ConcurrentFileChange(
                f"parent directory changed while editing: {parent.path}"
            )


def check_file_snapshot_identity(snapshot: FileSnapshot) -> None:
    """Check path, symlink, target, and captured-parent identities without reading.

    This check is intentionally identity-only for use after a domain parser has
    loaded the file: it adds no second content read. It is a best-effort race
    detector, not a lock or a transactional guarantee.
    """
    _check_parent_identities(snapshot)
    if snapshot.original is None:
        try:
            if _missing(snapshot.path):
                return
        except OSError as error:
            raise ConcurrentFileChange(
                f"selected file changed while editing: {snapshot.path}"
            ) from error
        raise ConcurrentFileChange(
            f"selected file was created while editing: {snapshot.path}"
        )

    try:
        current_link = (
            os.readlink(snapshot.path) if snapshot.path.is_symlink() else None
        )
        current_target = (
            snapshot.path.resolve(strict=True)
            if current_link is not None
            else snapshot.path
        )
        current_file_identity = _identity(snapshot.path)
        current_target_identity = _identity(snapshot.target_path)
    except OSError as error:
        raise ConcurrentFileChange(
            f"selected file disappeared or changed while editing: {snapshot.path}"
        ) from error
    if (
        current_link != snapshot.symlink_target
        or current_target != snapshot.target_path
        or current_file_identity != snapshot.file_identity
        or current_target_identity != snapshot.target_identity
    ):
        raise ConcurrentFileChange(
            f"selected file identity changed while editing: {snapshot.path}"
        )


def check_file_snapshot_current(snapshot: FileSnapshot) -> None:
    """Check captured identities and compare the current bytes with the snapshot."""
    check_file_snapshot_identity(snapshot)
    if snapshot.original is None:
        return
    try:
        current = _read_regular_file(snapshot.path)
    except OSError as error:
        raise ConcurrentFileChange(
            f"selected file could not be read while editing: {snapshot.path}"
        ) from error
    if current != snapshot.original:
        raise ConcurrentFileChange(
            f"selected file contents changed while editing: {snapshot.path}"
        )


def save_file_snapshot(snapshot: FileSnapshot, content: bytes) -> None:
    """Atomically replace a selected regular file with arbitrary bytes.

    Parent creation happens only here, after the caller has chosen to save. The
    existing mode is preserved, and staging uses the resolved physical parent so
    it remains beside the target even when the selected spelling contains links
    or ``..``. Complete bytes are flushed and fsynced before the final
    best-effort check and ``os.replace``. Staging files are removed on failure.
    These checks do not lock out writers or promise isolation between the final
    check and replacement.
    """
    check_file_snapshot_current(snapshot)
    destination = snapshot.target_path
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging_parent = parent.resolve(strict=True)
    check_file_snapshot_current(snapshot)
    mode = (
        stat.S_IMODE(destination.stat().st_mode)
        if snapshot.original is not None
        else None
    )
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=staging_parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary_name, mode)
        check_file_snapshot_current(snapshot)
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


__all__ = [
    "ConcurrentFileChange",
    "FileSnapshot",
    "ParentDirectoryIdentity",
    "capture_file_snapshot",
    "check_file_snapshot_current",
    "check_file_snapshot_identity",
    "save_file_snapshot",
]
