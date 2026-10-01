"""Domain-neutral round-trip YAML editing and source-envelope tests."""

from __future__ import annotations

import pytest
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

from rimpack.cli.yaml_editing import (
    YamlEditError,
    create_yaml_document,
    dump_yaml_document,
    load_yaml_document,
    string_scalar,
)


def test_native_mapping_and_list_edits_keep_lexical_strings_and_quote_styles() -> None:
    """Edit ruamel-native trees without config-specific coercion or cleanup."""
    source = (
        "root:\n"
        "  00123: leading-zero-id\n"
        "  '': empty-key\n"
        "  null: literal-null-key\n"
        "  single: 'old single'\n"
        '  double: "old double"\n'
        "  unicode: 日本語とcafé\n"
        '  control: "line\\nwith\\ttab"\n'
        "items:\n"
        "  - first\n"
    ).encode()
    document = load_yaml_document(source)
    mapping = document.root
    assert isinstance(mapping, CommentedMap)

    lexical = mapping["root"]
    assert set(lexical) == {
        "00123",
        "",
        "null",
        "single",
        "double",
        "unicode",
        "control",
    }
    assert lexical["00123"] == "leading-zero-id"
    assert lexical[""] == "empty-key"
    assert lexical["null"] == "literal-null-key"
    assert isinstance(lexical["single"], SingleQuotedScalarString)
    assert isinstance(lexical["double"], DoubleQuotedScalarString)
    assert lexical["unicode"] == "日本語とcafé"
    assert lexical["control"] == "line\nwith\ttab"

    lexical["single"] = string_scalar("changed single", lexical["single"])
    lexical["double"] = string_scalar("changed double", lexical["double"])
    mapping["items"].append(string_scalar("second\titem"))
    mapping["items"].append(string_scalar("third\nline"))
    output = dump_yaml_document(document, mapping)
    reloaded = load_yaml_document(output).root

    assert reloaded["root"]["00123"] == "leading-zero-id"
    assert reloaded["root"][""] == "empty-key"
    assert reloaded["root"]["null"] == "literal-null-key"
    assert isinstance(reloaded["root"]["single"], SingleQuotedScalarString)
    assert isinstance(reloaded["root"]["double"], DoubleQuotedScalarString)
    assert reloaded["items"] == ["first", "second\titem", "third\nline"]


def test_generic_loader_does_not_change_empty_roots_or_optional_collections() -> None:
    """Leave empty roots and collection semantics to the caller's domain adapter."""
    assert load_yaml_document(None).root is None
    assert load_yaml_document(b"").root is None
    document = load_yaml_document(b"empty_list: []\nnull_word: null\n")
    assert document.root["empty_list"] == []
    assert document.root["null_word"] == "null"


def test_create_yaml_document_wraps_supplied_root_without_parsing_source() -> None:
    """Permit callers to attach an already validated native root to source bytes."""
    root = CommentedMap({"value": "created"})
    document = create_yaml_document(b"not: [parsed", root)

    assert document.root is root
    assert dump_yaml_document(document, root) == b"value: created\n"


@pytest.mark.parametrize(
    ("source", "tail", "expected_bom"),
    [
        (
            b"key: value\n...\n",
            b"...\n",
            b"",
        ),
        (
            b"key: value\r\n... # inline\tcomment\r\n # after marker\ttext\r\n  \r\n",
            b"... # inline\tcomment\r\n # after marker\ttext\r\n  \r\n",
            b"",
        ),
        (
            b"\xef\xbb\xbfkey: value\n... # final marker",
            b"... # final marker",
            b"\xef\xbb\xbf",
        ),
        (
            b"key: value\n... # marker\n# after marker",
            b"... # marker\n# after marker",
            b"",
        ),
    ],
)
def test_terminal_document_marker_tail_is_restored_verbatim(
    source: bytes, tail: bytes, expected_bom: bytes
) -> None:
    """Keep legal end-marker lines and every trailing comment byte exactly once."""
    prefix = b"\xef\xbb\xbf" if source.startswith(b"\xef\xbb\xbf") else b""
    assert prefix == expected_bom
    document = load_yaml_document(source)
    assert document.document_end_tail.encode() == tail

    output = dump_yaml_document(document, document.root)

    assert output.startswith(expected_bom)
    assert output.endswith(tail)
    decoded = output.decode("utf-8-sig")
    assert decoded.count("...") == 1
    assert decoded.count("# after marker") == (1 if b"# after marker" in tail else 0)


def test_marker_looking_text_in_quoted_and_block_scalars_is_not_a_tail() -> None:
    """Do not mistake scalar content for a column-zero document-end marker."""
    source = (
        'quoted: "text containing ... and # not a comment"\n'
        "block: |\n"
        "  ...\n"
        "  # part of the scalar\n"
    ).encode()
    document = load_yaml_document(source)

    assert document.document_end_tail == ""
    assert document.root["quoted"] == "text containing ... and # not a comment"
    assert document.root["block"] == "...\n# part of the scalar\n"


def test_malformed_and_multiple_documents_are_not_hidden_by_tail_extraction() -> None:
    """Load the complete YAML before retaining a terminal source tail."""
    for source in (b"value: [\n...\n# tail\n", b"value: one\n---\nvalue: two\n"):
        with pytest.raises(YamlEditError) as error:
            load_yaml_document(source)
        assert error.value.__cause__ is not None


def test_yaml_edit_errors_retain_the_underlying_encoding_cause() -> None:
    """Expose a clear shared error while retaining the decoding exception."""
    with pytest.raises(YamlEditError) as error:
        load_yaml_document(b"value: \xff")
    assert isinstance(error.value.__cause__, UnicodeDecodeError)


def test_document_dump_preserves_a_supplied_preamble_and_bom() -> None:
    """Join a narrow source preamble to emitted native YAML without losing BOM."""
    source = b"\xef\xbb\xbf# source comment\r\n"
    root = CommentedMap({"value": "new"})
    document = create_yaml_document(source, root)

    output = dump_yaml_document(document, root, preamble="# source comment\r\n")

    assert output == b"\xef\xbb\xbf# source comment\r\nvalue: new\n"
