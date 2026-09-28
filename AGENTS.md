# Repository guidance

## Docstrings

Write clear, human-friendly docstrings for every function, including private helpers. Explain what the function is for and describe important behavior or edge cases. Add a short example when it helps readers understand the expected input or output; skip examples that would only add noise. Document public data classes and types where useful, and keep every docstring accurate as the code changes.

## Documentation responsibilities

Read [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) before implementation work
and keep relevant technical decisions and caveats there. Clearly distinguish
planned guidance from implemented behavior.

Specifications describe product intent. Agents must not edit specifications merely
to document implementation details, library limitations, or internal design
choices; use implementation notes instead. Specification changes must reflect an
actual change or clarification of intended product behavior.

## Project references

- [PATTERNS.md](PATTERNS.md) describes design preferences.
- [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) records implementation guidance and technical caveats.
- [Specifications](spec/): [initial spec](spec/initial_spec.md), [aliases](spec/aliases.md), and [sorting](spec/sorting.md).
