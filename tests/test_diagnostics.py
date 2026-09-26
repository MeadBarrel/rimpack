"""Tests for structured XML diagnostics and their text renderer."""

from dataclasses import FrozenInstanceError

import pytest

from rimpack.sdk.diagnostics import (
    Diagnostic,
    DiagnosticGroup,
    DuplicateFieldDiagnostic,
    EmptyValueDiagnostic,
    InvalidAttributeDiagnostic,
    InvalidVersionTagDiagnostic,
    MissingFieldDiagnostic,
    StrayTextDiagnostic,
    UnexpectedElementDiagnostic,
    UnknownAttributeDiagnostic,
    UnknownFieldDiagnostic,
    XmlContext,
    group_diagnostics,
    render_diagnostics,
)


def test_groups_require_context_and_nonempty_immutable_diagnostics():
    """Create nonempty frozen groups and omit empty groups via the helper."""
    child = EmptyValueDiagnostic()
    context = XmlContext("li", 2)
    group = DiagnosticGroup(context, (child,))
    records = (
        context,
        group,
        StrayTextDiagnostic("stray", "<li> entries"),
        MissingFieldDiagnostic("packageId"),
        child,
        DuplicateFieldDiagnostic("url", 2),
        UnexpectedElementDiagnostic("b", "plain text"),
        InvalidVersionTagDiagnostic("broken"),
        UnknownFieldDiagnostic("legacy"),
        UnknownAttributeDiagnostic("source", "old"),
        InvalidAttributeDiagnostic("flag", "bad", ("True", "False")),
    )

    assert group_diagnostics(context, ()) == ()
    assert group_diagnostics(context, (child,)) == (group,)
    assert all(not hasattr(record, "__dict__") for record in records)
    with pytest.raises(FrozenInstanceError):
        group.context = XmlContext("other")  # type: ignore[misc]
    with pytest.raises(TypeError, match="must be a tuple"):
        DiagnosticGroup(context, [child])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot be empty"):
        DiagnosticGroup(context, ())


def test_xml_context_uses_one_based_sibling_indices():
    """Render source-based sibling positions in a concise context label."""
    assert str(XmlContext("v1.6")) == "v1.6"
    assert str(XmlContext("li", 2)) == "li[2]"
    with pytest.raises(ValueError, match="one-based"):
        XmlContext("li", 0)


def test_render_diagnostics_shows_nested_context():
    """Indent nested groups and render leaf diagnostics readably."""
    diagnostics: tuple[Diagnostic, ...] = (
        DiagnosticGroup(
            XmlContext("ModMetaData"),
            (
                DiagnosticGroup(
                    XmlContext("authors"),
                    (
                        StrayTextDiagnostic("unexpected", "<li> entries"),
                        DiagnosticGroup(
                            XmlContext("li", 2),
                            (EmptyValueDiagnostic(),),
                        ),
                    ),
                ),
            ),
        ),
    )

    assert render_diagnostics(diagnostics) == (
        "ModMetaData:\n"
        "  authors:\n"
        "    - Ignored text outside <li> entries: 'unexpected'\n"
        "    li[2]:\n"
        "      - Empty value"
    )
    assert str(diagnostics[0]) == render_diagnostics(diagnostics)
    assert render_diagnostics(()) == ""


def test_render_diagnostics_covers_leaf_record_types():
    """Keep readable messages for each structured diagnostic payload."""
    diagnostics: tuple[Diagnostic, ...] = (
        MissingFieldDiagnostic("packageId"),
        DuplicateFieldDiagnostic("url", 2),
        UnexpectedElementDiagnostic("b", "plain text"),
        InvalidVersionTagDiagnostic("broken"),
        UnknownFieldDiagnostic("legacyField"),
        UnknownAttributeDiagnostic("source", "legacy"),
        InvalidAttributeDiagnostic(
            "IgnoreIfNoMatchingField", "maybe", ("True", "False")
        ),
    )

    assert render_diagnostics(diagnostics) == (
        "- Missing <packageId>\n"
        "- Duplicate <url> field (2 occurrences)\n"
        "- Unexpected <b>; expected plain text\n"
        "- Invalid version tag <broken>\n"
        "- Unknown field <legacyField>\n"
        "- Unknown attribute 'source'='legacy'\n"
        "- Invalid value 'maybe' for attribute 'IgnoreIfNoMatchingField'; "
        "expected 'True', 'False'"
    )
    assert str(StrayTextDiagnostic("x", "<li> entries")) == (
        "- Ignored text outside <li> entries: 'x'"
    )


def test_renderer_escapes_control_characters_without_mutating_payload():
    """Escape control characters for display while preserving exact source text."""
    payload = "first\nsecond\t\x01"
    diagnostic = StrayTextDiagnostic(payload, "<li> entries")

    rendered = render_diagnostics((diagnostic,))

    assert rendered == (
        "- Ignored text outside <li> entries: 'first\\nsecond\\t\\u0001'"
    )
    assert diagnostic.text == payload


def test_renderer_truncates_only_the_display_of_long_text():
    """Limit rendered text to 120 source characters without changing the record."""
    payload = "x" * 121
    diagnostic = StrayTextDiagnostic(payload, "<li> entries")

    rendered = render_diagnostics((diagnostic,))

    assert rendered == f"- Ignored text outside <li> entries: '{'x' * 119}…'"
    assert diagnostic.text == payload
