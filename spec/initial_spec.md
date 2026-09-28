## Description

Rimpack is a Git-friendly command-line mod manager for RimWorld.

A modpack is defined by `modpack.yml` and one or more module files.

Typical structure:

```text
modpack.yml
modules/
  <module-name>.yml
```

## Examples

`modpack.yml`

```yaml
modules:
  - modules/ludeon.yml
  - modules/frameworks.yml
  - modules/core.yml

aliases:
  - aliases.yml
```

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

A module contains a name and an ordered list of mods.

### `name`

The module name. It must match the ASCII identifier pattern
`[A-Za-z_][A-Za-z0-9_]*`.

### `mods`

A required ordered list of mods contained in the module. The list may be empty.

Each mod is represented by a mapping with exactly one reference field (`pid`, `wid`,
`loc`, or `als`), and may also contain `before` and/or `after`. No other fields are
currently supported. Mod entries and repeated constraints retain their source order;
parsing does not sort or deduplicate them.

A reference identifies or locates a mod. The reference-only mappings used in
`before` and `after` contain exactly one reference field and cannot themselves
contain additional fields.

## References

### `wid`

Steam Workshop published-file ID. It is a positive unsigned 64-bit integer, from
`1` through `18446744073709551615`. It may be written as a positive decimal YAML
integer or an ASCII decimal digit string whose numeric value is within that range.
Booleans, floats, zero, negative values, and other strings are invalid. The parser
stores the value as text; digit strings retain leading zeros whether quoted or
unquoted. The loader does not interpret leading-zero numbers as octal.

Tagged scalar syntax, such as `!!int`, is outside the supported module-file contract;
users should use the untagged scalar forms shown here. The implementation may recognize
some explicit tags for compatibility, but malformed or otherwise tagged scalars are not
required to produce `ModuleParseError`.

For predictable identifiers, the loader treats only `true`/`false` spellings as
booleans; `yes`, `no`, `on`, and `off` are strings. Quote `true` or `false` when
using those words as string identifiers.

```yaml
wid: 2009463077
wid: "0001234567"
```

### `pid`

RimWorld package ID. The initial parser accepts nonempty ASCII values without
whitespace and preserves their spelling in the module record. This initial character
restriction is a parser support policy, not a claim that RimWorld universally forbids
non-ASCII package IDs.

Package ID matching is case-insensitive. Internal package references use lowercase
canonical values, while source records retain the original spelling.

```yaml
pid: brrainz.harmony
```

### `loc`

Path to a local mod. It must be a nonempty, non-whitespace string without NUL. The
parser converts it to a path without checking whether the target exists or is usable;
meaningful spaces in a path are preserved. Path syntax follows the host platform.

A parsed path remains unresolved. During later resolution, relative paths are anchored
to the modpack root directory, defined as the directory containing `modpack.yml`.
Absolute paths remain absolute.

```yaml
loc: mods/my-local-mod
```

### `als`

Reference to a mod alias. Alias names use the same ASCII identifier pattern as module
names. Parsing preserves the alias reference without checking whether it is defined.
Alias definitions and resolution semantics are described in [aliases.md](aliases.md).

```yaml
als: my_aliased_mod
```

## Additional mod fields

Mod entries may contain additional fields in addition to their reference.

### `before`

An optional list of reference-only mappings. It adds a sorting constraint requiring
this mod to load before the referenced mods. If omitted, it is treated as empty; if
present, it must be a YAML list (which may be empty, but cannot be null).

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
this mod to load after the referenced mods. If omitted, it is treated as empty; if
present, it must be a YAML list (which may be empty, but cannot be null).

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

A module file is one YAML document whose root is a mapping containing the required
`name` and `mods` fields. Empty files/documents, non-mapping roots, multiple documents,
duplicate mapping keys, unknown fields, unsupported collection tags (including YAML
sets, ordered maps, and pairs collections), YAML merge keys, and recursive YAML aliases
are errors. Safe acyclic YAML anchors and aliases are accepted.

Tagged scalar syntax (`!!timestamp`, `!!bool`, `!!float`, `!!int`, and similar forms)
is outside the supported module format; users must use the ordinary untagged scalar
forms. The parser's `ModuleParseError` guarantee applies to supported untagged values
and structural YAML errors. Behavior for malformed or explicitly tagged scalar values
is unspecified and may expose an underlying PyYAML exception.

Invalid supported values are errors; the parser does not silently discard mods or
constraints and does not return a partially parsed module. YAML construction, syntax,
and duplicate-key errors retain their existing source locations; syntax and duplicate-key
errors also include a line and column when the YAML loader provides them. Pydantic validation errors
are reported as an aggregate: `ModuleParseError.location` is `$`, and its message has
one line per returned detail, in Pydantic order. Each line includes a tuple location,
which may contain union-branch names, the validation message, and its error type. These
validation errors do not fabricate YAML line or column numbers. Raw input, validator
context, and documentation URLs are omitted from the rendered details, but this is not
a secrecy guarantee because locations or validator messages may contain user data and
the suppressed exception context remains inspectable. Filesystem access errors remain
filesystem errors.
