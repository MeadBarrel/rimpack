"""Public source-aware exceptions shared by SDK parsers."""

from pathlib import Path


class ParseError(ValueError):
    """Shared source-aware error behavior for parser-specific exception types."""

    def __init__(
        self,
        path: Path,
        location: str,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        """Store error details; source positions, when available, are one-based."""
        self.path = path
        self.location = location
        self.message = message
        self.line = line
        self.column = column
        super().__init__(self.__str__())

    def __str__(self) -> str:
        """Render the file, optional source coordinates, and logical location."""
        source = str(self.path)
        if self.line is not None:
            source += f":{self.line}"
            if self.column is not None:
                source += f":{self.column}"
        return f"{source}: {self.location}: {self.message}"
