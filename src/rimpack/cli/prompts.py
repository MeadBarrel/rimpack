"""Typed prompt_toolkit adapters and literal Rich output for setup."""

from __future__ import annotations

from typing import Sequence

from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.shortcuts import choice, prompt
from rich.console import Console
from rich.text import Text

from rimpack.cli.setup import (
    ChoiceOption,
    SetupCancelled,
    SetupUI,
    escape_terminal_controls,
)


def _styled_prompt(message: str) -> StyleAndTextTuples:
    """Style prompt text while visually de-emphasizing a trailing requirement."""
    safe_message = escape_terminal_controls(message)
    required = " (required)"
    if safe_message.endswith(required):
        return [
            ("bold fg:ansicyan", safe_message[: -len(required)]),
            ("fg:ansibrightblack", required),
        ]
    return [("bold fg:ansicyan", safe_message)]


def prompt_choice(
    message: str,
    options: Sequence[ChoiceOption],
    *,
    default: str,
) -> str:
    """Collect one stable option key and translate terminal cancellation."""
    try:
        selected = choice(
            _styled_prompt(message),
            options=[
                (option.key, escape_terminal_controls(option.label))
                for option in options
            ],
            default=default,
        )
    except (EOFError, KeyboardInterrupt) as error:
        raise SetupCancelled("interactive setup was cancelled") from error
    if not isinstance(selected, str):
        raise RuntimeError("prompt_toolkit returned a non-string choice key")
    return selected


def prompt_path(message: str) -> str:
    """Read raw path text with directory completion but no existence validation."""
    try:
        prompt_message: StyleAndTextTuples = _styled_prompt(message)
        prompt_message.append(("bold fg:ansicyan", ": "))
        result = prompt(
            prompt_message,
            completer=PathCompleter(only_directories=True, expanduser=False),
            complete_while_typing=True,
        )
    except (EOFError, KeyboardInterrupt) as error:
        raise SetupCancelled("interactive setup was cancelled") from error
    if not isinstance(result, str):
        raise RuntimeError("prompt_toolkit returned non-text path input")
    return result


def prompt_confirmation(message: str, *, default: bool = False) -> bool:
    """Collect an explicit typed yes/no choice with a conservative default."""
    default_key = "yes" if default else "no"
    selected = prompt_choice(
        message,
        (ChoiceOption("yes", "Yes"), ChoiceOption("no", "No")),
        default=default_key,
    )
    return selected == "yes"


class PromptToolkitUI(SetupUI):
    """Implement the wizard's typed UI protocol with prompt_toolkit and Rich."""

    def choose(
        self,
        message: str,
        options: Sequence[ChoiceOption],
        *,
        default: str,
    ) -> str:
        """Return one offered stable choice key from the interactive menu."""
        return prompt_choice(message, options, default=default)

    def enter_path(self, message: str) -> str:
        """Return path completion input without checking whether it exists."""
        return prompt_path(message)

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """Return an explicit confirmation, defaulting to no unless requested."""
        return prompt_confirmation(message, default=default)

    def show(self, message: str, *, kind: str = "info") -> None:
        """Print literal text, coloring review labels and values without markup."""
        console = Console(stderr=kind == "error", highlight=False)
        style = {"warning": "yellow", "error": "red"}.get(kind)
        safe_lines = [escape_terminal_controls(line) for line in message.split("\n")]
        if kind == "review":
            rendered = Text()
            for index, line in enumerate(safe_lines):
                if index:
                    rendered.append("\n")
                if line.startswith("  - "):
                    rendered.append(line, style="yellow")
                    continue
                if ": " not in line:
                    rendered.append(line, style="bold cyan")
                    continue
                label, value = line.split(": ", 1)
                rendered.append(f"{label}: ", style="bold cyan")
                if " -> " in value:
                    old, new = value.split(" -> ", 1)
                    rendered.append(old, style="green")
                    rendered.append(" -> ", style="dim")
                    rendered.append(new, style="green")
                elif label == "Warnings" and value == "none":
                    rendered.append(value, style="dim")
                elif label == "Warnings":
                    rendered.append(value, style="yellow")
                else:
                    rendered.append(value, style="green")
            console.print(rendered)
            return
        console.print(Text("\n".join(safe_lines)), style=style)
