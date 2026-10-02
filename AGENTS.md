# Repository guidance

## Docstrings

Write clear, human-friendly docstrings for every function, including private helpers.

Explain what the function is for and describe important behavior, assumptions, or edge cases. Add a short example when it helps readers understand the expected input or output; skip examples that would only add noise.

Document public data classes and types where useful, and keep every docstring accurate as the code changes.

## Implementation workflow

Before implementing a change:

- Read [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md).
- Read [PATTERNS.md](PATTERNS.md) and follow the relevant design preferences.
- Read the [specification index](spec/index.md) and the specifications relevant to the requested behavior.
- Inspect the existing implementation and tests around the affected area before deciding how to change it.
- Identify existing abstractions, utilities, and conventions that can be reused instead of introducing parallel mechanisms.

Treat specifications as the source of truth for intended product behavior.

Keep changes focused on the requested work. Avoid unrelated cleanup, broad refactoring, or speculative abstractions unless they are necessary for the implementation.

Prefer extending existing designs over introducing new architectural concepts. When a new abstraction is necessary, keep it as small and narrowly scoped as possible.

Preserve separation of concerns. Put functionality in the module that owns the relevant responsibility rather than placing it wherever it is easiest to access.

When behavior changes, add or update tests that demonstrate the intended behavior. Include relevant edge cases and regression coverage when the change fixes a bug.

After implementation:

- Run the relevant tests, type checking, linting, and other project validation available for the affected code.
- Review the resulting diff for accidental changes, unnecessary complexity, duplicated functionality, stale comments, and inaccurate docstrings.
- Verify that the implementation still matches the relevant specifications.
- Update local comments and docstrings when implementation details or assumptions changed.
- Consider whether the work introduced a durable technical decision or caveat that belongs in `IMPLEMENTATION_NOTES.md`; follow the documentation rules below before changing it.

Do not treat passing tests as sufficient evidence that a change is correct. Also review the implementation against the specification, surrounding architecture, and important edge cases.

## Specifications

Specifications describe product intent and expected behavior. They are requirements, not implementation notes.

Read the [specification index](spec/index.md) and all relevant topic specifications before implementation or specification work.

Do not change specifications as part of ordinary implementation work.

If a user request contradicts an existing specification, do not implement the contradictory behavior immediately. Explain the conflict and ask the user for permission to update the relevant specification. Only after the user approves the specification change should the specification be updated and the contradictory behavior implemented.

If a request would extend or materially reinterpret an existing specification without clearly contradicting it, surface that discrepancy and ask whether the specification should be updated before proceeding.

Only edit specifications when the user has explicitly requested a specification change or has approved one after a conflict was identified.

Keep the specification index up to date when adding, splitting, renaming, or removing specifications.

## Documentation responsibilities

Read [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) before implementation work.

Use `IMPLEMENTATION_NOTES.md` only for durable, non-obvious technical decisions and cross-cutting implementation guidance, such as:

- architectural or design decisions whose rationale would otherwise be lost;
- constraints imposed by external systems, formats, libraries, compatibility requirements, or platform behavior;
- decisions that future agents should preserve during refactoring;
- caveats or invariants that affect multiple modules or future implementation work;
- intentionally deferred work or known limitations that future agents need to understand.

Do not use `IMPLEMENTATION_NOTES.md` as an implementation diary. Do not add notes that merely restate behavior obvious from the code.

Prefer an in-code comment or docstring when the information:

- explains why a particular local implementation is written in a non-obvious way;
- documents an invariant, workaround, edge case, or assumption specific to one function, class, or module;
- would become irrelevant if that code were removed or substantially rewritten.

As a rule of thumb, if the information should remain useful after the surrounding implementation is refactored, it may belong in `IMPLEMENTATION_NOTES.md`. If it primarily explains the code immediately next to it, keep it in the code.

Before changing [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md), ask the user for approval.

Clearly distinguish planned guidance from implemented behavior.

## Project references

- [PATTERNS.md](PATTERNS.md) describes design preferences.
- [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) records durable implementation guidance, technical decisions, and caveats.
- [Specification index](spec/index.md) is the entry point for product intent.
