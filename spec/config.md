# Global configuration

The SDK settings parser and loader implement the schema, validation, and path
selection described here. CLI wiring, setup, and mod scanning remain planned.
CLI configuration selection is specified in [cli.md](cli.md), and the interactive
setup wizard is specified in [setup.md](setup.md).

## Scope and storage

Global settings describe the user's machine and mod-discovery sources. They are
separate from `modpack.yml` and module files and are not part of a modpack.

The default settings file is `~/.rimpack/settings.yml` on every platform, where
`~` denotes the current user's home directory. For example, on Windows:

```text
C:\Users\lai\.rimpack\settings.yml
```

The CLI can select an alternative configuration folder or file through
[`--config`](cli.md#config-selection).

## Schema

The settings file is a YAML mapping. All recognized fields are optional.
Empty, whitespace-only, and comment-only files mean empty settings. This
exception does not apply to scalar roots (including quoted empty strings) or
files containing only document markers.

| Field | Value | Meaning when omitted |
| --- | --- | --- |
| `rimworld_path` | Path string to the RimWorld installation root | Installation is unconfigured. |
| `workshop_path` | Path string to the RimWorld-specific Workshop content root | Workshop source is unconfigured. |
| `data_path` | Path string overriding the bundled-content root | Derive from `rimworld_path / Data`, if available. |
| `mods_path` | Path string overriding the installation's local-mod root | Derive from `rimworld_path / Mods`, if available. |
| `extra_mod_paths` | List of path strings to additional mod-discovery roots | Empty list. |

`rimworld_path` points to the installation directory, not the executable or the
`Data` directory. `workshop_path` points to the RimWorld content directory,
typically `steamapps/workshop/content/294100`, not a Steam library root or an
individual Workshop item.

Example:

```yaml
rimworld_path: 'D:\Games\Steam\steamapps\common\RimWorld'
workshop_path: 'D:\Games\Steam\steamapps\workshop\content\294100'
extra_mod_paths:
  - 'D:\RimWorldMods'
  - 'D:\Projects\MyMods'
```

In this example, the effective Data and Mods paths are derived from the
installation. Overrides may be supplied independently:

```yaml
data_path: ../game-data
mods_path: ~/RimWorldMods
```

## Path values and resolution

Every supplied path must be a nonempty, non-whitespace string without NUL.
Meaningful spaces are preserved; paths are not trimmed. Path syntax follows the
host platform. On Windows, drive-relative forms such as `C:game` are rejected:
use an absolute path such as `C:/game` or an ordinary relative path such as
`game`. Rimpack does not use Windows's remembered per-drive working directories.

Omission is the only way to leave an optional path unset. A blank YAML value
such as `rimworld_path:` or an empty string such as `rimworld_path: ""` is an
error. The same path-value validation applies to entries in `extra_mod_paths`.
For the collection itself, omission, a blank YAML value, or a quoted empty
string means an empty list. Whitespace-only scalars and other non-list values
are invalid; list order and duplicates are retained.

For every path value in the settings file:

1. Expand a leading `~` referring to the current user's home directory.
2. If the resulting path is relative, anchor it to the directory containing the
   selected settings file.
3. Absolute paths remain absolute.

Rimpack does not expand environment-variable expressions. Changing the command's
working directory does not change the meaning of paths in the same settings
file. The separate rules for locating the file through `--config` are defined in
[cli.md](cli.md#config-selection).

Resolving a path does not require its target to exist or be accessible. Schema
validation and filesystem availability checks are separate operations.

## Data and Mods properties

The settings schema is represented by a dataclass exposing properties for the
effective Data and Mods paths. The YAML fields are optional overrides; the
properties apply the following defaults:

- Effective Data path: the resolved `data_path` override, otherwise the resolved
  `rimworld_path / Data`, otherwise `None`.
- Effective Mods path: the resolved `mods_path` override, otherwise the resolved
  `rimworld_path / Mods`, otherwise `None`.

An explicit override does not require `rimworld_path` to be configured. Accessing
these properties does not inspect the filesystem or perform discovery. Derived
paths do not need to be written as explicit overrides in the settings file.

An unavailable explicit override remains the selected path; it does not fall
back to the installation-derived path.

## Loading and validation

Loading settings does not discover installation paths, run setup, or create a
configuration folder or file. Paths can be configured manually; automatic
installation discovery is not a prerequisite for using settings.

Unrecognized field names produce warnings and are ignored. For example,
`workhop_path` must be reported as an unknown field, not silently treated as
`workshop_path`.

Invalid YAML, an invalid document structure, or a malformed value in a recognized
field is an error. Such errors must not be converted into empty settings or a
successful partially loaded configuration. An existing settings file that cannot
be read is also an error.

The CLI's handling of an absent default file versus an explicitly selected
missing file is defined in [cli.md](cli.md#missing-configuration).

## Mod-discovery sources

The effective Data and Mods paths, a configured Workshop path, and the entries in
`extra_mod_paths` supply mod-discovery roots. Unconfigured sources do not supply
roots.

Extra folders contain mod directories as immediate children. Discovery under an
extra folder is not recursive; nested collections must be listed separately.

If a discovery source is missing, is not a directory, or cannot be accessed,
report a warning identifying that source and skip it. Continue with usable
sources rather than failing solely because one source is unavailable. Do not
silently substitute another path.

This specification does not define duplicate-mod resolution or precedence
between discovery sources.
