# Modules

Module files are included by a [modpack](modpack.md). Mod-reference formats are
specified in [references.md](references.md); effective ordering is specified in
[sorting.md](sorting.md).

## Examples

`modules/ludeon.yml`

```yaml
name: ludeon

mods:
  - pid: ludeon.rimworld
  - pid: ludeon.rimworld.royalty
```

`modules/frameworks.yml`

```yaml
name: frameworks

mods:
  - wid: 2009463077  # Harmony (brrainz.harmony)
```

## Module format

A module contains a name and an optionally specified ordered list of mods. If
omitted, the module has no mods.

### `name`

The module name. It must match the ASCII identifier pattern
`[A-Za-z_][A-Za-z0-9_]*`.

### `mods`

An optional ordered list of mods contained in the module. If omitted, it is treated
as empty. An explicitly empty list may be written with a blank scalar (`mods:` or
`mods: ""`); a whitespace-only value is not empty. Flow-style empty lists (`[]`)
are not supported.

Each mod is represented by a mapping with exactly one reference field (`pid`, `wid`,
or `loc`), and may also contain `before` and/or `after`. No other fields are
currently supported. Mod entries and repeated constraints retain their source order;
parsing does not sort or deduplicate them.

A reference identifies or locates a mod. The reference-only mappings used in
`before` and `after` contain exactly one reference field and cannot themselves
contain additional fields.

## Additional mod fields

Mod entries may contain additional fields in addition to their reference.

### `before`

An optional list of reference-only mappings. It adds a sorting constraint requiring
this mod to load before the referenced mods. If omitted or specified as a blank
scalar (`before:` or `before: ""`), it is treated as empty. Otherwise it must be a
block-style YAML list; flow-style collections such as `[]` are not supported.

```yaml
name: example

mods:
  - pid: my.mod
    before:
      - pid: another.mod
      - wid: 1234567
```

### `after`

An optional list of reference-only mappings. It adds a sorting constraint requiring
this mod to load after the referenced mods. If omitted or specified as a blank
scalar (`after:` or `after: ""`), it is treated as empty. Otherwise it must be a
block-style YAML list; flow-style collections such as `[]` are not supported.

```yaml
name: example

mods:
  - pid: my.mod
    after:
      - pid: another.mod
      - wid: 1234567
```

Sorting behavior, constraint resolution, and ordering semantics are described in [sorting.md](sorting.md).

## Module parsing and validation

A module file is one YAML document with a mapping root and a required `name` field.
`mods` may be omitted; a missing or blank `mods`, `before`, or `after` value means
an empty list. Empty files/documents, non-mapping roots, multiple documents, duplicate
mapping keys, unknown fields, flow-style collections, explicit tags, YAML anchors,
and YAML aliases are errors. Collections with entries use block-style YAML.

All untagged scalar values are read as text. Their validity depends on the destination
field: for example, `pid: null` is the text `null`, while `wid: null` is invalid
because it is not a positive decimal ID. YAML scalar spellings are not implicitly
converted to booleans, numbers, nulls, or dates.

Invalid values are errors; the parser does not silently discard mods or constraints
and does not return a partially parsed module. Parsing and validation failures are
reported as `ModuleParseError`; parser errors include line and column when available.
`ModuleParseError.location` is `$` for module-level validation, and its message has
one line per returned validation detail, in validation order. Each line includes a
tuple location, which may contain union-branch names, the validation message, and its
error type. Validation errors do not fabricate YAML line or column numbers. Raw input,
validator context, and documentation URLs are omitted from rendered validation details,
but this is not a secrecy guarantee because locations or validator messages may contain
user data and the suppressed exception context remains inspectable. Filesystem access
errors remain filesystem errors.
