# Mod references

References identify or locate mods. They appear in module mod entries and in
`before` and `after` constraints; mapping structure is specified in
[modules.md](modules.md#module-format).

## `wid`

Steam Workshop published-file ID. An integer must have a numeric value from `1`
through `18446744073709551615`. Booleans, floats, zero, negative integers, and values
above the maximum are invalid. A quoted ID must contain only ASCII decimal digits and
have a value in the same uint64 range.

## `pid`

RimWorld package ID. The parser accepts nonempty ASCII string values without
whitespace. Values interpreted as booleans, numbers, nulls, or dates are not strings;
quote such values when they are intended as package-ID text. This character restriction
is a parser support policy, not a claim that RimWorld universally forbids non-ASCII
package IDs.

Package ID matching is case-insensitive.

```yaml
pid: brrainz.harmony
```

## `loc`

Path to a local mod. It must be a nonempty, non-whitespace YAML string without NUL.
Plain values implicitly resolved as booleans, numbers, nulls, or dates are invalid; use
quotes when such a spelling is intended as path text. The parser converts the value to
a path without checking whether the target exists or is usable; meaningful spaces in a
path are preserved. Path syntax follows the host platform.

A parsed path remains unresolved. During later resolution, relative paths are anchored
to the modpack root directory, defined as the directory containing `modpack.yml`.
Absolute paths remain absolute.

```yaml
loc: mods/my-local-mod
```

## `als` (future)

Alias references are not currently supported. Module parsing rejects `als` in `mods`,
`before`, and `after`, including when it accompanies a supported reference field. The
future alias format and resolution behavior are specified in [aliases.md](aliases.md).
