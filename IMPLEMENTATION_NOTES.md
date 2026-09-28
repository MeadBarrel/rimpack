# Implementation notes

Technical decisions, library constraints, and implementation caveats belong here.
Specifications describe product intent; these notes do not silently change their
requirements. Mark planned guidance explicitly until it is implemented.

## Configuration reading and editing (planned)

Use StrictYAML for reading and validation, and ruamel.yaml for comment-aware
editing. This is the intended implementation direction, not current behavior.

### Empty lists

StrictYAML rejects flow-style empty lists (`[]`). When an optional list becomes
empty, remove its mapping key instead of emitting `[]` or a blank value. The
reader should interpret an omitted optional list as empty.

- For `before` and `after`, omit the field when its last reference is removed.
  Omission already means no ordering constraints.
- Do not apply this rule blindly to required lists. `mods` is currently required;
  omitting it would require an explicit decision that missing `mods` means an
  empty module, followed by corresponding reader/schema changes.
- Alias `resolution` must remain nonempty. Removing its field does not make an
  empty resolution valid; reject the edit rather than silently remove the alias.

### Validation and preservation

Use StrictYAML-decoded values as the semantic source of truth: ruamel.yaml can
implicitly type values and lose meaningful identifier spelling when those Python
values are used directly (for example, leading zeros in Workshop IDs).

Before saving, validate serialized output with StrictYAML and compare its
schema-normalized domain values with the intended result. Default ruamel.yaml
serialization is not guaranteed to produce StrictYAML-compatible output.

Comment and formatting preservation need separate tests, especially for list
insertion, removal, and reordering. Semantic validation cannot detect lost or
misattached comments; removing an empty field must not silently discard unrelated
comments.
