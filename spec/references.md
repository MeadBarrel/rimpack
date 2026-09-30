# Mod references

References identify or locate mods. They appear in module mod entries and in
`before` and `after` constraints; mapping structure is specified in
[modules.md](modules.md#module-format).

## `wid`

Steam Workshop published-file ID. It must contain only ASCII decimal digits and
have a numeric value from `1` through `18446744073709551615`. Leading zeros are
preserved, and do not change the numeric range check. Signs, digit separators,
zero, and values above the maximum are invalid.

Untagged scalar values in module files are text, not implicitly typed numbers,
booleans, nulls, or dates. Thus a bare `wid: 2009463077` and quoted
`wid: "2009463077"` both provide the same decimal text. Other values such as
`true` are rejected for `wid` because they are not decimal digits. Explicit YAML
tags are not supported.

```yaml
wid: 2009463077
wid: "0001234567"
```

## `pid`

RimWorld package ID. The initial parser accepts nonempty ASCII values without
whitespace and preserves their spelling in the module record. This initial character
restriction is a parser support policy, not a claim that RimWorld universally forbids
non-ASCII package IDs.

Package ID matching is case-insensitive. Internal package references use lowercase
canonical values, while source records retain the original spelling.

```yaml
pid: brrainz.harmony
```

## `loc`

Path to a local mod. It must be a nonempty, non-whitespace string without NUL. The
parser converts it to a path without checking whether the target exists or is usable;
meaningful spaces in a path are preserved. Path syntax follows the host platform.

A parsed path remains unresolved. During later resolution, relative paths are anchored
to the modpack root directory, defined as the directory containing `modpack.yml`.
Absolute paths remain absolute.

```yaml
loc: mods/my-local-mod
```

## `als` (future, out of scope)

The planned `als` reference identifies a mod alias. Alias names will use the same
ASCII identifier pattern as module names. Future parsing will preserve the alias
reference without checking whether it is defined; definitions and resolution
semantics are retained in [aliases.md](aliases.md).

Current module parsing rejects `als` in `mods`, `before`, and `after`, including
when it accompanies a supported reference field. The following example is for
future implementation only:

```yaml
als: my_aliased_mod
```
