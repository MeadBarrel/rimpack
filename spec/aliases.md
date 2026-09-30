# Aliases (future, out of scope)

Mod-alias support is planned for a future version and is not part of the current
scope. This document preserves the intended future behavior: all requirements
and examples below apply only when alias support is implemented. The `aliases`
modpack field is not currently supported, and module entries and ordering
constraints reject `als` references.

## Description

Aliases provide stable names for mods that may be identified or located in multiple ways.

An alias can be used anywhere a normal mod reference is accepted by using the `als` reference type.

Example:

```yaml id="4pbk99"
mods:
  - als: harmony
```

Aliases are defined in files referenced by `modpack.yml`.

Example:

```yaml id="4d7mcn"
aliases:
  - aliases.yml
```

## Alias file format

An alias file is a mapping from alias names to alias definitions.

Example:

```yaml id="oiqxth"
harmony:
  resolution:
    - pid: brrainz.harmony
    - wid: 2009463077

my_local_mod:
  resolution:
    - pid: my.mod
    - wid: 1234567
    - loc: mods/my-local-mod
```

Each top-level key is the alias name.

Alias names must match the ASCII identifier pattern `[A-Za-z_][A-Za-z0-9_]*`.

Alias names must be unique across all alias files loaded by the modpack.

## Alias definition

An alias definition contains a `resolution` field and may contain additional mod fields.

Example:

```yaml id="jq21w7"
my_aliased_mod:
  resolution:
    - pid: my.mod
    - wid: 1234567
    - loc: mods/my-local-mod

  before:
    - pid: another.mod
```

## `resolution`

`resolution` is a list of references describing ways to identify or locate the aliased mod.

Example:

```yaml id="xkwwt6"
resolution:
  - pid: my.mod
  - wid: 1234567
  - loc: mods/my-local-mod
```

Each item in `resolution` must be a valid mod reference.

The references in `resolution` all refer to the same logical mod.

Rimpack uses them when resolving the alias against available mods.

Resolution must be deterministic. If the available references resolve to conflicting mods, Rimpack must report an ambiguity instead of silently selecting one.

An alias must contain at least one resolution reference.

## Using aliases

Aliases are referenced using `als`.

```yaml id="ugp7lf"
mods:
  - als: harmony
```

An alias may also be used anywhere another mod reference is accepted:

```yaml id="oeyhmz"
mods:
  - pid: my.mod
    before:
      - als: harmony
```

## Additional mod fields

An alias may define the same additional fields as a normal mod entry.

Example:

```yaml id="0b8gmu"
framework:
  resolution:
    - pid: framework.mod
    - wid: 1234567

  before:
    - pid: dependent.mod
```

Sorting fields and their semantics are described in [sorting.md](sorting.md).

## Alias references inside aliases

Aliases must not reference themselves, either directly or indirectly.

Invalid direct recursion:

```yaml id="fdzkgw"
foo:
  resolution:
    - als: foo
```

Invalid indirect recursion:

```yaml id="zh1fj5"
foo:
  resolution:
    - als: bar

bar:
  resolution:
    - als: foo
```

Recursive alias resolution is an error.

## Path handling

Relative `loc` references inside alias definitions are resolved relative to the modpack root directory, defined as the directory containing `modpack.yml`.

Example:

```yaml id="lx0u6y"
my_local_mod:
  resolution:
    - loc: mods/my-local-mod
```

## Validation

Rimpack must report an error when:

- an alias name is duplicated;
- an alias has no `resolution` entries;
- a resolution entry is not a valid mod reference;
- an alias refers to an unknown alias;
- alias references form a cycle;
- multiple resolution references identify conflicting mods.

Unknown aliases must not be silently ignored.
