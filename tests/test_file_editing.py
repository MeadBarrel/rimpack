"""Shared regular-file snapshot and change-detection behavior."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from rimpack.cli.file_editing import (
    ConcurrentFileChange,
    capture_file_snapshot,
    check_file_snapshot_current,
    check_file_snapshot_identity,
)


def make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    """Create a symlink or skip when host permissions do not allow one."""
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlinks are unavailable: {error}")


def test_capture_anchors_relative_paths_without_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anchor relative paths to cwd while treating tilde as an ordinary name."""
    monkeypatch.chdir(tmp_path)
    path = Path("~/plain-file")
    path.parent.mkdir()
    path.write_bytes(b"raw")

    snapshot = capture_file_snapshot(path)

    assert snapshot.path == tmp_path / path
    assert snapshot.original == b"raw"
    assert snapshot.target_path == snapshot.path


def test_absent_and_empty_files_have_distinct_snapshots(tmp_path: Path) -> None:
    """Use None only for absence and retain zero-byte source as real content."""
    absent = capture_file_snapshot(tmp_path / "absent")
    empty_path = tmp_path / "empty"
    empty_path.touch()
    empty = capture_file_snapshot(empty_path)

    assert absent.original is None
    assert empty.original == b""


def test_directories_and_special_files_are_rejected_before_reading(
    tmp_path: Path,
) -> None:
    """Refuse targets that are not ordinary regular files."""
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(OSError):
        capture_file_snapshot(directory)

    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe"
        os.mkfifo(fifo)
        with pytest.raises(OSError):
            capture_file_snapshot(fifo)

    if hasattr(socket, "AF_UNIX"):
        socket_path = tmp_path / "socket"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            try:
                server.bind(str(socket_path))
            except OSError as error:
                pytest.skip(f"filesystem sockets are unavailable: {error}")
            with pytest.raises(OSError):
                capture_file_snapshot(socket_path)


def test_concurrent_modification_creation_and_deletion_are_detected(
    tmp_path: Path,
) -> None:
    """Detect changed bytes and changed existence after snapshot capture."""
    target = tmp_path / "source"
    target.write_bytes(b"before")
    modified = capture_file_snapshot(target)
    target.write_bytes(b"changed")
    with pytest.raises(ConcurrentFileChange):
        check_file_snapshot_current(modified)
    assert target.read_bytes() == b"changed"

    target.unlink()
    absent = capture_file_snapshot(target)
    target.write_bytes(b"another writer")
    with pytest.raises(ConcurrentFileChange, match="created"):
        check_file_snapshot_identity(absent)
    assert target.read_bytes() == b"another writer"

    target.unlink()
    recreated = capture_file_snapshot(target)
    target.write_bytes(b"writer")
    with pytest.raises(ConcurrentFileChange):
        check_file_snapshot_identity(recreated)


def test_deleting_an_existing_file_is_detected_after_capture(tmp_path: Path) -> None:
    """Detect that an existing file disappeared after its snapshot was read."""
    target = tmp_path / "source"
    target.write_bytes(b"before")
    snapshot = capture_file_snapshot(target)
    target.unlink()

    with pytest.raises(ConcurrentFileChange):
        check_file_snapshot_identity(snapshot)
    assert not target.exists()


def test_change_during_snapshot_read_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject source bytes read while a competing writer changes file identity."""
    target = tmp_path / "source"
    target.write_bytes(b"before")
    original_read = Path.read_bytes

    def changing_read(path: Path) -> bytes:
        """Mutate the target after returning its originally captured content."""
        content = original_read(path)
        if path == target:
            target.write_bytes(b"concurrent")
        return content

    monkeypatch.setattr(Path, "read_bytes", changing_read)
    with pytest.raises(ConcurrentFileChange):
        capture_file_snapshot(target)
    assert target.read_bytes() == b"concurrent"


def test_concurrent_replacement_is_detected_even_when_bytes_match(
    tmp_path: Path,
) -> None:
    """Compare identities as well as content when a file is atomically replaced."""
    target = tmp_path / "source"
    target.write_bytes(b"same")
    snapshot = capture_file_snapshot(target)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"same")
    os.replace(replacement, target)

    with pytest.raises(ConcurrentFileChange):
        check_file_snapshot_identity(snapshot)


def test_dangling_symlinks_are_not_treated_as_absent(tmp_path: Path) -> None:
    """Reject dangling selected links and ancestors instead of creating targets."""
    selected = tmp_path / "dangling"
    make_symlink(selected, tmp_path / "missing-target")
    with pytest.raises(OSError):
        capture_file_snapshot(selected)

    dangling_parent = tmp_path / "dangling-parent"
    make_symlink(dangling_parent, tmp_path / "missing-directory", directory=True)
    with pytest.raises(OSError):
        capture_file_snapshot(dangling_parent / "settings")


def test_retargeted_parent_symlink_is_detected(tmp_path: Path) -> None:
    """Reject a selected parent link that resolves somewhere else after capture."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "settings").write_bytes(b"source")
    selected_parent = tmp_path / "profile"
    make_symlink(selected_parent, first, directory=True)
    snapshot = capture_file_snapshot(selected_parent / "settings")

    selected_parent.unlink()
    make_symlink(selected_parent, second, directory=True)

    with pytest.raises(ConcurrentFileChange, match="parent directory changed"):
        check_file_snapshot_identity(snapshot)
