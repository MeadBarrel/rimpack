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

The module name.

It must be a valid identifier and must not contain spaces or special characters.

### `mods`

An ordered list of mods contained in the module.

Each mod is represented by a mapping containing a reference and, optionally, additional fields.

A reference identifies or locates the mod.

## References

### `wid`

Steam Workshop ID.

```yaml
wid: 2009463077
```

### `pid`

RimWorld package ID.

Package ID matching is case-insensitive.

```yaml
pid: brrainz.harmony
```

### `loc`

Path to a local mod.

Relative paths are resolved relative to the modpack root directory, defined as the directory containing `modpack.yml`.

```yaml
loc: mods/my-local-mod
```

### `als`

Reference to a mod alias.

Alias definitions and resolution semantics are described in [aliases.md](aliases.md).

```yaml
als: my_aliased_mod
```

## Additional mod fields

Mod entries may contain additional fields in addition to their reference.

### `before`

Adds a sorting constraint requiring this mod to load before the referenced mods.

```yaml
name: example

mods:
  - pid: my.mod
    before:
      - pid: another.mod
      - wid: 1234567
```

### `after`

Adds a sorting constraint requiring this mod to load after the referenced mods.

```yaml
name: example

mods:
  - pid: my.mod
    after:
      - pid: another.mod
      - wid: 1234567
```

Sorting behavior, constraint resolution, and ordering semantics are described in [sorting.md](sorting.md).
