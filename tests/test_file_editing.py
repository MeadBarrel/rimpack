"""Shared file snapshots and atomic replacement behavior."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path

import pytest

from rimpack.cli import file_editing
from rimpack.cli.file_editing import (
    ConcurrentFileChange,
    capture_file_snapshot,
    check_file_snapshot_current,
    check_file_snapshot_identity,
    save_file_snapshot,
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


def test_generic_saver_handles_non_yaml_non_utf8_bytes_and_extensionless_paths(
    tmp_path: Path,
) -> None:
    """Replace arbitrary bytes without applying YAML, encoding, or suffix rules."""
    target = tmp_path / "settings"
    target.write_bytes(b"\xff\x00before")
    snapshot = capture_file_snapshot(target)
    content = b"\x00\xfeafter\n"

    save_file_snapshot(snapshot, content)

    assert target.read_bytes() == content


def test_capture_creates_nothing_and_save_creates_parent_directories(
    tmp_path: Path,
) -> None:
    """Keep snapshotting read-only and defer parent creation until an explicit save."""
    target = tmp_path / "new" / "nested" / "config"
    snapshot = capture_file_snapshot(target)

    assert not target.parent.exists()
    save_file_snapshot(snapshot, b"new content")
    assert target.read_bytes() == b"new content"


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
    """Refuse to save over source bytes or path existence changed after capture."""
    target = tmp_path / "source"
    target.write_bytes(b"before")
    modified = capture_file_snapshot(target)
    target.write_bytes(b"changed")
    with pytest.raises(ConcurrentFileChange):
        check_file_snapshot_current(modified)
    with pytest.raises(ConcurrentFileChange):
        save_file_snapshot(modified, b"replacement")
    assert target.read_bytes() == b"changed"

    target.unlink()
    absent = capture_file_snapshot(target)
    target.write_bytes(b"another writer")
    with pytest.raises(ConcurrentFileChange, match="created"):
        save_file_snapshot(absent, b"replacement")
    assert target.read_bytes() == b"another writer"

    target.unlink()
    recreated = capture_file_snapshot(target)
    target.write_bytes(b"writer")
    with pytest.raises(ConcurrentFileChange):
        check_file_snapshot_identity(recreated)


def test_deleting_an_existing_file_is_detected_before_save(tmp_path: Path) -> None:
    """Do not turn a captured existing file into a replacement after deletion."""
    target = tmp_path / "source"
    target.write_bytes(b"before")
    snapshot = capture_file_snapshot(target)
    target.unlink()

    with pytest.raises(ConcurrentFileChange):
        save_file_snapshot(snapshot, b"replacement")
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


def test_change_during_staging_is_detected_and_temporary_file_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve an observed competing edit that occurs before final replacement."""
    target = tmp_path / "settings"
    target.write_bytes(b"original")
    snapshot = capture_file_snapshot(target)
    original_fsync = file_editing.os.fsync
    concurrent = b"concurrent edit"

    def changed_fsync(descriptor: int) -> None:
        """Simulate a writer immediately after staging bytes reach disk."""
        original_fsync(descriptor)
        target.write_bytes(concurrent)

    monkeypatch.setattr(file_editing.os, "fsync", changed_fsync)
    with pytest.raises(ConcurrentFileChange):
        save_file_snapshot(snapshot, b"replacement")

    assert target.read_bytes() == concurrent
    assert list(tmp_path.glob(".settings.*.tmp")) == []


def test_replacement_failure_cleans_staging_file_and_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean same-directory staging after an atomic-replace error."""
    target = tmp_path / "settings"
    target.write_bytes(b"original")
    snapshot = capture_file_snapshot(target)

    def fail_replace(source: object, destination: object) -> None:
        """Inject an OS replacement failure after successful staging."""
        raise OSError("injected replacement failure")

    monkeypatch.setattr(file_editing.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replacement failure"):
        save_file_snapshot(snapshot, b"replacement")

    assert target.read_bytes() == b"original"
    assert list(tmp_path.glob(".settings.*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission bits")
def test_existing_mode_is_preserved(tmp_path: Path) -> None:
    """Keep an existing file's permission bits on its atomic replacement."""
    target = tmp_path / "settings"
    target.write_bytes(b"original")
    target.chmod(0o640)
    snapshot = capture_file_snapshot(target)

    save_file_snapshot(snapshot, b"replacement")

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_selected_file_symlink_is_retained_while_its_target_is_replaced(
    tmp_path: Path,
) -> None:
    """Follow a selected file link for reads and replace its target on save."""
    target = tmp_path / "real-file"
    target.write_bytes(b"before")
    selected = tmp_path / "selected-file"
    make_symlink(selected, target)
    snapshot = capture_file_snapshot(selected)

    save_file_snapshot(snapshot, b"after")

    assert selected.is_symlink()
    assert target.read_bytes() == b"after"


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
