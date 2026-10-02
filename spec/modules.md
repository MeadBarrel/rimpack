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
as empty. It may also be empty as `null`, an exactly empty scalar (`mods:` or
`mods: ""`), or an empty sequence (`[]`). A whitespace-only string is not empty.
Block and flow sequences are supported; list order and repetitions are retained.

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
scalar (`before:` or `before: ""`), null, or an empty sequence (`[]`), it is treated
as empty. Otherwise it must be a YAML sequence; block and flow styles are supported.

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
scalar (`after:` or `after: ""`), null, or an empty sequence (`[]`), it is treated
as empty. Otherwise it must be a YAML sequence; block and flow styles are supported.

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

A module file is one YAML document with a mapping root and a required string `name`.
Empty files/documents, null or other non-mapping roots, multiple documents, duplicate
mapping keys, and unknown module fields are errors.

`name`, `pid`, and `loc` require string values. Values interpreted as booleans,
numbers, nulls, or dates are not strings; quote values when text is intended. `wid`
accepts a positive uint64 as an integer value or as a quoted ASCII decimal-digit string.
See [references.md](references.md#wid) for the identifier rules. For `mods`, `before`,
and `after`, omission, null, an exactly empty string, and an empty sequence all mean an
empty collection. Whitespace-only strings and other non-sequence values are invalid.

Invalid values are errors; the parser does not silently discard mods or constraints
and does not return a partially parsed module. Parsing and validation failures are
reported as `ModuleParseError`; parser errors include line and column when available.
Validation errors do not fabricate YAML line or column numbers. Filesystem access
errors remain filesystem errors.
