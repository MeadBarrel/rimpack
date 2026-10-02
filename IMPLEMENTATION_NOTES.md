# Implementation notes

Technical decisions, library constraints, and implementation caveats belong here.
Specifications describe product intent; these notes record non-obvious guidance
and caveats. Clearly distinguish implemented behavior from planned work.

## Module and settings YAML reading (implemented)

The SDK uses fresh safe ruamel loaders through `sdk._yaml` and passes native YAML
values to Pydantic. Keep scalar resolution consistent across SDK readers. Translate
only recognized source parsing failures, retaining available marks; unrelated
exceptions must surface. Unknown settings fields are ignored only after successful
safe parsing; malformed settings must not become empty or partially loaded.

Do not add custom alias-cycle, expansion, or parser resource limits without
revisiting that decision; control naturally raised recursion failures at the SDK
boundary. Internal reference constructors assume source records have already
validated their values; they are not input-validation boundaries.

## Stable topological sorting (implemented)

The sorter protects each preferred prefix before optimizing for movement. Its
deterministic candidate heuristic is deliberately not a global minimum inversion
or movement optimizer. Preserve the prefix guarantee independently of tie-breaking
or candidate improvements.

## YAML editing (implemented)

The round-trip editor uses ruamel's normal YAML resolver to keep untouched values
consistent with SDK parsing. Preserve user comments and source-envelope data where
supported, but do not promise formatting identity: semantic validation cannot
detect lost or misattached comments.

## YAML writer guidance (planned)

Omit empty optional list fields rather than emitting `[]`.

## CLI and setup dependencies (implemented)

The selected stack for the shared CLI and `rimpack setup` is:

- Typer for commands, options, and help; do not add Click as a separate direct
  dependency.
- `prompt_toolkit>=3.0.52,<4` for interactive selection, text input,
  confirmations, and path completion. Its generic `choice()` preserves the type
  of option values; text prompts return `str` and confirmations return `bool`.
  Prefer it directly over Questionary or InquirerPy, whose answer APIs return
  `Any` and would require an additional typed boundary.
- Rich for readable warnings and final settings summaries.
- ruamel.yaml for comment-aware settings updates, using the same normal scalar
  resolution as the SDK safe reader. Follow the YAML editing guidance above;
  round-trip serialization alone does not guarantee unchanged formatting.

Keep prompt calls behind thin, typed Rimpack helpers for consistent styling,
cancellation handling, and testing, without leaking `Any` into wizard logic.
Path completion must not enforce filesystem existence: unavailable paths need
an explicit warning-override step, as specified in `spec/setup.md`.

The selected dependencies are declared in `pyproject.toml` and used by the
current CLI and setup code.

## Steam RimWorld path discovery (implemented)

- SDK Steam discovery is Windows-only and is called explicitly; importing the SDK
  does not touch the registry or filesystem. Each call gathers registry roots,
  conventional environment/Program Files candidates, and fixed paths on logical
  drives, then expands only each candidate's `steamapps/libraryfolders.vdf`.
  Candidate libraries are checked directly as well as through those metadata
  files. No drive, game, or Workshop tree is walked.
- The small KeyValues reader is intentionally not a general VDF implementation.
  It is byte-, token-, and nesting-bounded; it handles quoted/bare scalars,
  escaped quotes/backslashes, comments, and the legacy scalar plus modern nested
  numeric library entries. It trusts only numeric library records and their
  direct `path` fields, and only the direct `appid`/`installdir` fields under the
  app manifest's `AppState` block. Malformed, ambiguous, unreadable, or oversized
  metadata rejects that record/candidate without stopping other discovery.
- A manifest install directory must be one safe Windows path component. The
  resulting existing game directory must resolve under that library's `common`
  directory and contain a known RimWorld executable plus a known game-data
  directory. Workshop content is reported only when the library's exact
  `workshop/content/294100` directory exists; an empty directory is valid.
  Results preserve the first discovered path spelling, deduplicate with Windows
  case-insensitive normalization, and sort by that normalized key.
