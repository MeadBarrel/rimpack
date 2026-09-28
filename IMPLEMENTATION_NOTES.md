# Implementation notes

Technical decisions, library constraints, and implementation caveats belong here.
Specifications describe product intent; these notes record how that behavior is
implemented. Clearly distinguish implemented behavior from planned work.

## Module YAML reading (implemented)

- `parse_module_yaml` uses StrictYAML to read the supported YAML subset, then
  validates decoded values with the existing Pydantic records. Reading is
  read-only; no editor/document object is exposed.
- Untagged scalar values remain text. Source-record validators handle IDs and
  paths; do not add implicit YAML scalar typing. Internal reference constructors
  assume values have already been validated by source records; they are not
  input-validation boundaries. The package-ID reference lowercases its value to
  provide case-insensitive identity.
- `EmptyableList[T]` in `rimpack.sdk._validation` is an opt-in Pydantic tuple
  alias. Its before-validator changes only the exactly empty string `""` to an
  empty list before tuple validation. It preserves fail-fast item validation.
  Use this type for future fields that intentionally accept blank-as-empty
  collection values; do not add parser field-name checks or global coercion.
- `Module.mods` defaults to an empty tuple. Fields using `EmptyableList` also
  accept an explicitly blank value, including a quoted empty string. Whitespace-
  only strings, `None`, and other wrong types remain invalid. Flow `[]` is not
  supported by the reader.
- For future writers, omit empty optional list fields rather than emitting `[]`.
  Omitted `mods` also means empty. Alias `resolution` must remain nonempty; this
  module-reader change does not alter alias validation.
- Convert StrictYAML parser errors to `ModuleParseError`, retaining source marks
  where available. StrictYAML 1.7.3 may wrap an invalid-character `ReaderError`
  in `AttributeError`; translate that case only when the chained context is a
  `ReaderError`, and let unrelated `AttributeError`s surface. Keep Pydantic
  validation details sanitized and do not invent source coordinates. Filesystem
  errors remain filesystem errors.

## YAML editing (planned)

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
