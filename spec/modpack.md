# Modpacks

A modpack is defined by `modpack.yml` and one or more module files.

## Directory layout

Typical structure:

```text
modpack.yml
modules/
  <module-name>.yml
```

The modpack root directory is the directory containing `modpack.yml`. Relative
`loc` references are anchored to this root during resolution, as specified in
[references.md](references.md#loc).

## `modpack.yml`

The `modules` field lists module files. Their supplied order contributes to the
preferred mod order described in [sorting.md](sorting.md).

`modpack.yml`

```yaml
modules:
  - modules/ludeon.yml
  - modules/frameworks.yml
  - modules/core.yml
```

The module format and examples are specified in [modules.md](modules.md).

## Future aliases

Mod aliases are planned for a future version and are out of current scope. The
`aliases` modpack field and `als` references are not currently supported; the
future design is retained in [aliases.md](aliases.md).
