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
