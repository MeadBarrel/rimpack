"""Structured diagnostics and readable rendering for XML and configuration parsers."""

from dataclasses import dataclass


class Diagnostic:
    """Base type for a parser diagnostic or a group of diagnostics."""

    __slots__ = ()

    def __str__(self) -> str:
        """Render this diagnostic as a concise human-readable string."""
        return render_diagnostics((self,))


@dataclass(frozen=True, slots=True)
class XmlContext:
    """Identify an XML element by its local tag and optional sibling index.

    ``index`` is one-based and is present only when siblings share the same tag.
    """

    tag: str
    index: int | None = None

    def __post_init__(self) -> None:
        """Reject indices that cannot identify a one-based sibling occurrence."""
        if self.index is not None and self.index < 1:
            raise ValueError("XML context indices are one-based")

    def __str__(self) -> str:
        """Render the element name, including its index when present."""
        if self.index is None:
            return self.tag
        return f"{self.tag}[{self.index}]"


@dataclass(frozen=True, slots=True)
class DiagnosticGroup(Diagnostic):
    """Attach child diagnostics to the XML element where they were found."""

    context: XmlContext
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        """Require a nonempty immutable collection of child diagnostics."""
        if not isinstance(self.diagnostics, tuple):
            raise TypeError("DiagnosticGroup.diagnostics must be a tuple")
        if not self.diagnostics:
            raise ValueError("DiagnosticGroup cannot be empty")
        if any(not isinstance(item, Diagnostic) for item in self.diagnostics):
            raise TypeError("DiagnosticGroup entries must be Diagnostic instances")


@dataclass(frozen=True, slots=True)
class StrayTextDiagnostic(Diagnostic):
    """Record exact non-whitespace text discarded outside expected children."""

    text: str
    expected_content: str


@dataclass(frozen=True, slots=True)
class MissingFieldDiagnostic(Diagnostic):
    """Identify a child field or metadata value that is missing."""

    tag: str


@dataclass(frozen=True, slots=True)
class EmptyValueDiagnostic(Diagnostic):
    """Identify a present field or entry whose trimmed text is empty."""


@dataclass(frozen=True, slots=True)
class DuplicateFieldDiagnostic(Diagnostic):
    """Identify a field that appears more than once under one parent."""

    tag: str
    count: int

    def __post_init__(self) -> None:
        """Require at least two occurrences for a duplicate field report."""
        if self.count < 2:
            raise ValueError("DuplicateFieldDiagnostic.count must be at least 2")


@dataclass(frozen=True, slots=True)
class UnexpectedElementDiagnostic(Diagnostic):
    """Describe an XML element where a different shape was expected."""

    tag: str
    expected: str


@dataclass(frozen=True, slots=True)
class InvalidVersionTagDiagnostic(Diagnostic):
    """Identify a version group whose element tag is not a supported version."""

    tag: str


@dataclass(frozen=True, slots=True)
class UnknownFieldDiagnostic(Diagnostic):
    """Identify an XML field not modeled by the parser."""

    tag: str


@dataclass(frozen=True, slots=True)
class UnknownConfigFieldDiagnostic(Diagnostic):
    """Identify an ignored configuration key without XML element formatting."""

    name: str


@dataclass(frozen=True, slots=True)
class UnknownAttributeDiagnostic(Diagnostic):
    """Identify an XML attribute not modeled by the parser."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class InvalidAttributeDiagnostic(Diagnostic):
    """Record an invalid value for a recognized XML attribute."""

    name: str
    value: str
    expected_values: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require expected spellings to be stored immutably."""
        if not isinstance(self.expected_values, tuple):
            raise TypeError(
                "InvalidAttributeDiagnostic.expected_values must be a tuple"
            )


def group_diagnostics(
    context: XmlContext, diagnostics: tuple[Diagnostic, ...]
) -> tuple[Diagnostic, ...]:
    """Wrap child diagnostics in context, omitting empty groups.

    Returning tuples makes it easy for a parent parser to compose diagnostic
    results without a shared mutable sink.
    """
    if not diagnostics:
        return ()
    return (DiagnosticGroup(context, diagnostics),)


def _quoted_text(text: str, *, limit: int = 120) -> str:
    """Escape control characters and abbreviate text for display only.

    At most ``limit`` source characters are shown; the stored diagnostic text is
    never modified. Truncation is marked with an ellipsis.
    """
    shortened = text if len(text) <= limit else f"{text[: limit - 1]}…"
    escaped: list[str] = []
    for character in shortened:
        if character == "\\":
            escaped.append("\\\\")
        elif character == "'":
            escaped.append("\\'")
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif character.isprintable():
            escaped.append(character)
        elif ord(character) <= 0xFFFF:
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(f"\\U{ord(character):08x}")
    return "'" + "".join(escaped) + "'"


def _render_leaf(diagnostic: Diagnostic) -> str:
    """Render one diagnostic that has no child diagnostics."""
    if isinstance(diagnostic, StrayTextDiagnostic):
        return (
            f"Ignored text outside {diagnostic.expected_content}: "
            f"{_quoted_text(diagnostic.text)}"
        )
    if isinstance(diagnostic, MissingFieldDiagnostic):
        return f"Missing <{diagnostic.tag}>"
    if isinstance(diagnostic, EmptyValueDiagnostic):
        return "Empty value"
    if isinstance(diagnostic, DuplicateFieldDiagnostic):
        return f"Duplicate <{diagnostic.tag}> field ({diagnostic.count} occurrences)"
    if isinstance(diagnostic, UnexpectedElementDiagnostic):
        return f"Unexpected <{diagnostic.tag}>; expected {diagnostic.expected}"
    if isinstance(diagnostic, InvalidVersionTagDiagnostic):
        return f"Invalid version tag <{diagnostic.tag}>"
    if isinstance(diagnostic, UnknownConfigFieldDiagnostic):
        return f"Ignored config field {_quoted_text(diagnostic.name)}"
    if isinstance(diagnostic, UnknownFieldDiagnostic):
        return f"Unknown field <{diagnostic.tag}>"
    if isinstance(diagnostic, UnknownAttributeDiagnostic):
        return (
            f"Unknown attribute {_quoted_text(diagnostic.name)}="
            f"{_quoted_text(diagnostic.value)}"
        )
    if isinstance(diagnostic, InvalidAttributeDiagnostic):
        expected = ", ".join(
            _quoted_text(value) for value in diagnostic.expected_values
        )
        return (
            f"Invalid value {_quoted_text(diagnostic.value)} for attribute "
            f"{_quoted_text(diagnostic.name)}; expected {expected}"
        )
    raise TypeError(f"Unsupported diagnostic type: {type(diagnostic).__name__}")


def _render_node(diagnostic: Diagnostic, indent: int, lines: list[str]) -> None:
    """Append one diagnostic tree node using two spaces per nesting level."""
    prefix = " " * indent
    if isinstance(diagnostic, DiagnosticGroup):
        lines.append(f"{prefix}{diagnostic.context}:")
        for child in diagnostic.diagnostics:
            _render_node(child, indent + 2, lines)
        return
    lines.append(f"{prefix}- {_render_leaf(diagnostic)}")


def render_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> str:
    """Render structured diagnostics as an indented human-readable tree.

    Text payloads are escaped and limited to 120 source characters in the
    display; diagnostic records retain their exact original values. Empty input
    renders as an empty string.
    """
    lines: list[str] = []
    for diagnostic in diagnostics:
        _render_node(diagnostic, 0, lines)
    return "\n".join(lines)
