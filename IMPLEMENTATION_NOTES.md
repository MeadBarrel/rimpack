# Implementation notes

Technical decisions, library constraints, and implementation caveats belong here.
Specifications describe product intent; these notes record non-obvious guidance
and caveats. Clearly distinguish implemented behavior from planned work.

## Module YAML reading (implemented)

- Internal reference constructors assume source records have already validated
  their values; they are not input-validation boundaries. Workshop IDs retain
  leading zeros in source records, but internal `WidReference` identities strip
  them so numerically identical IDs match in ordering constraints. Normalize
  as text to avoid integer conversion limits on heavily zero-padded valid IDs.
- Use `EmptyableList` for future collection fields that intentionally accept a
  blank value as empty, rather than adding parser field-name checks or global
  coercion.
- StrictYAML 1.7.3 may wrap an invalid-character `ReaderError` in an
  `AttributeError`. Translate only when the chained context is a `ReaderError`;
  unrelated `AttributeError`s must surface.

## Stable topological sorting (implemented)

The sorter normalizes resolved `before` and `after` declarations into indexed,
deduplicated adjacency sets. Missing references are ignored; indexed graph
operations mean item values need stable hashing/equality but never ordering.
For each node, urgency is the minimum original index among itself and all
reachable descendants. A reverse-topological dynamic program computes these
priorities in linear graph time rather than repeating reachability searches.

Urgency groups encode the prefix guarantee: a node can enter an early group
only if it is itself in that preferred prefix or is a prerequisite of an item
in it. The implementation generates forward-priority and reverse-latest-sink
Kahn candidates, then independently chooses the lower-inversion candidate for
each group; ties use the lexicographically smaller original-index sequence.
This deterministic best-of-two heuristic deliberately prioritizes prefix
protection and does not guarantee a globally minimum inversion or movement
metric. The indexed adjacency storage is `O(V + E)`; graph passes and candidate
construction/scoring take `O(E + V log V)` time.

## YAML editing (planned)

For future writers, omit empty optional list fields rather than emitting `[]`.

Use ruamel.yaml for comment-aware editing only if/when editing is implemented.
StrictYAML remains the reader/validator and source of semantic values. Do not
trust ruamel's implicitly typed values for lexical identifiers such as Workshop
IDs. Revalidate serialized output with StrictYAML and compare decoded domain
values with the intended result before saving.

Default ruamel serialization is not guaranteed to use StrictYAML-compatible
syntax. Comment and formatting preservation need separate tests, especially for
list insertion, removal, and reordering. Semantic validation cannot detect lost
or misattached comments; removing an empty field must not silently discard
unrelated comments. No editing functionality is implemented by this note.

## CLI and setup dependencies (planned)

The selected stack for the shared CLI and `rimpack setup` is:

- Typer for commands, options, and help; do not add Click as a separate direct
  dependency.
- `prompt_toolkit>=3.0.52,<4` for interactive selection, text input,
  confirmations, and path completion. Its generic `choice()` preserves the type
  of option values; text prompts return `str` and confirmations return `bool`.
  Prefer it directly over Questionary or InquirerPy, whose answer APIs return
  `Any` and would require an additional typed boundary.
- Rich for readable warnings and final settings summaries.
- ruamel.yaml for comment-aware settings updates, with StrictYAML retained as
  the reader/validator. Follow the YAML editing guidance above; round-trip
  serialization alone does not guarantee unchanged formatting.

Keep prompt calls behind thin, typed Rimpack helpers for consistent styling,
cancellation handling, and testing, without leaking `Any` into wizard logic.
Path completion must not enforce filesystem existence: unavailable paths need
an explicit warning-override step, as specified in `spec/setup.md`.

This records the chosen stack only. Dependency additions and the CLI/setup
implementation remain planned.

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
- The disposable `.probes/steam-path-discovery/` run measured a 3.29145 ms median
  over ten warm runs on one Windows machine. This is evidence that bounded
  metadata discovery was inexpensive on that warm filesystem cache, not a cold
  start result or a guaranteed latency bound.
