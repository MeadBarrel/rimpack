"""Shared, domain-neutral mechanics for round-trip YAML edits."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.resolver import VersionedResolver
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    ScalarString,
    SingleQuotedScalarString,
)


class YamlEditError(ValueError):
    """Describe a YAML decoding, loading, or serialization failure."""


class _LexicalScalarResolver(VersionedResolver):
    """Keep implicit plain scalars as strings instead of resolving YAML types."""

    def resolve(self, kind: Any, value: Any, implicit: Any) -> Any:
        """Preserve plain scalar text, including empty and null-like words."""
        if kind is ScalarNode and implicit[0]:
            return super().resolve(kind, "lexical scalar", (False, False))
        return super().resolve(kind, value, implicit)


@dataclass(frozen=True, slots=True)
class YamlDocument:
    """Hold one native ruamel document and its source envelope for later dumping.

    ``root`` is ruamel's native tree (or ``None`` for an empty YAML document).
    The retained tail begins at a legal document-end marker and is kept verbatim.
    """

    original: bytes | None
    yaml: YAML
    root: object
    document_end_tail: str = ""


def _decode_source(source: bytes | None) -> str:
    """Decode optional UTF-8 source while allowing and removing its BOM."""
    if source is None:
        return ""
    try:
        return source.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise YamlEditError(f"YAML source is not valid UTF-8: {error}") from error


def create_round_trip_yaml(source: str) -> YAML:
    """Create a lexical, quote-preserving YAML reader and dumper.

    Implicit plain scalars remain strings, so values such as ``true``, ``1``,
    ``null``, and an empty mapping key do not become Python booleans, numbers,
    ``None``, or colliding mapping keys. Existing quote styles and explicit
    start markers are retained where ruamel can represent them.
    """
    yaml = YAML(typ="rt")
    yaml.Resolver = _LexicalScalarResolver
    yaml.preserve_quotes = True
    yaml.width = 1_000_000
    if _has_marker_line(source, "---"):
        yaml.explicit_start = True
    if _has_marker_line(source, "..."):
        yaml.explicit_end = True
    return yaml


def _line_content(line: str) -> str:
    """Return a line without its exact Python/YAML-recognized line ending."""
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\r", "\n", "\x85", "\u2028", "\u2029")):
        return line[:-1]
    return line


def _has_marker_line(source: str, marker: str) -> bool:
    """Detect a column-zero document marker with legal trailing text."""
    pattern = re.compile(re.escape(marker) + r"[ \t]*(?:#.*)?")
    return any(
        pattern.fullmatch(_line_content(line)) is not None
        for line in source.splitlines(keepends=True)
    )


def _is_blank_or_comment_line(line: str) -> bool:
    """Recognize blank lines and ASCII-indented comment lines in a YAML tail."""
    content = _line_content(line)
    return not content.strip() or content.lstrip(" \t").startswith("#")


def _document_end_tail(source: str) -> str:
    """Return a legal terminal document-marker tail without altering its bytes."""
    offset = 0
    lines = source.splitlines(keepends=True)
    for index, line in enumerate(lines):
        content = _line_content(line)
        if not re.fullmatch(r"\.\.\.[ \t]*(?:#.*)?", content):
            offset += len(line)
            continue
        if all(_is_blank_or_comment_line(tail) for tail in lines[index + 1 :]):
            return source[offset:]
        offset += len(line)
    return ""


def _new_yaml_document(source: bytes | None, text: str, root: object) -> YamlDocument:
    """Build the immutable document context shared by both construction paths."""
    try:
        yaml = create_round_trip_yaml(text)
    except Exception as error:
        raise YamlEditError(f"round-trip YAML setup failed: {error}") from error
    return YamlDocument(source, yaml, root, _document_end_tail(text))


def load_yaml_document(source: bytes | None) -> YamlDocument:
    """Decode and round-trip-load one complete YAML document without file access.

    The full source is loaded before its terminal marker tail is identified, so
    malformed input and multiple documents cannot be hidden by source splitting.
    Empty documents keep ruamel's native ``None`` root; callers decide whether
    that root is acceptable for their domain.
    """
    text = _decode_source(source)
    try:
        yaml = create_round_trip_yaml(text)
        root = yaml.load(text)
    except Exception as error:
        if isinstance(error, YamlEditError):
            raise
        raise YamlEditError(f"round-trip YAML loading failed: {error}") from error
    return YamlDocument(source, yaml, root, _document_end_tail(text))


def create_yaml_document(source: bytes | None, root: object) -> YamlDocument:
    """Wrap a supplied native ruamel root without parsing the source text.

    This supports callers that have independently validated a blank or
    comment-only source and want to create a mapping while preserving its source
    envelope. The input bytes are decoded for encoding and marker configuration,
    but are never passed to ruamel's YAML parser.
    """
    text = _decode_source(source)
    return _new_yaml_document(source, text, root)


def _preferred_newline(text: str) -> str:
    """Choose a separator for a new line without rewriting existing separators."""
    match = re.search(r"\r\n|[\r\n\x85\u2028\u2029]", text)
    return match.group(0) if match is not None else "\n"


def _ends_with_line_break(text: str) -> bool:
    """Return whether text already ends at any supported source line boundary."""
    return text.endswith(("\r", "\n", "\x85", "\u2028", "\u2029"))


def _without_terminal_bare_end_marker(serialized: str) -> str:
    """Remove only an emitter-generated bare terminal ``...`` marker."""
    match = re.search(r"(?m)^\.\.\.[ \t]*(?:\r\n|\r|\n)?\Z", serialized)
    return serialized[: match.start()] if match is not None else serialized


def dump_yaml_document(
    document: YamlDocument,
    root: object,
    *,
    preamble: str = "",
) -> bytes:
    """Serialize native nodes and restore their BOM, preamble, and retained tail.

    Ruamel remains responsible for all YAML node edits. A retained document-end
    marker and its trailing comments are appended once, verbatim, after removing
    any terminal bare marker generated by the emitter. ``preamble`` is a narrow
    caller-owned source envelope, not a general comment-transplant mechanism.
    """
    output = io.StringIO()
    try:
        if document.document_end_tail:
            document.yaml.explicit_end = False
        document.yaml.dump(root, output)
    except Exception as error:
        raise YamlEditError(f"round-trip YAML serialization failed: {error}") from error

    serialized = output.getvalue()
    if document.document_end_tail:
        serialized = _without_terminal_bare_end_marker(serialized)
    if preamble:
        if not _ends_with_line_break(preamble):
            preamble += _preferred_newline(preamble)
        serialized = preamble + serialized
    if document.document_end_tail:
        if serialized and not _ends_with_line_break(serialized):
            serialized += _preferred_newline(document.document_end_tail)
        serialized += document.document_end_tail

    try:
        encoded = serialized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise YamlEditError(
            f"round-trip YAML serialization produced invalid Unicode: {error}"
        ) from error
    if document.original is not None and document.original.startswith(b"\xef\xbb\xbf"):
        encoded = b"\xef\xbb\xbf" + encoded
    return encoded


def string_scalar(value: str, previous: object = None) -> str:
    """Represent a string safely while retaining a supported prior quote style.

    Nonprintable characters use double quotes so ruamel emits escaped YAML text.
    Otherwise, an existing ruamel scalar-string style is reused when possible;
    newly introduced strings use single quotes to keep lexical identifiers plain.
    """
    if any(not character.isprintable() for character in value):
        return DoubleQuotedScalarString(value)
    if isinstance(previous, ScalarString):
        return type(previous)(value)
    return SingleQuotedScalarString(value)


__all__ = [
    "YamlDocument",
    "YamlEditError",
    "create_round_trip_yaml",
    "create_yaml_document",
    "dump_yaml_document",
    "load_yaml_document",
    "string_scalar",
]
