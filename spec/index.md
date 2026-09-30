# Specification index

Rimpack is a Git-friendly command-line mod manager for RimWorld.

The specifications are organized by topic. Start here, then read the documents
relevant to the behavior being changed.

| Topic | Specification | Covers |
| --- | --- | --- |
| Modpacks | [modpack.md](modpack.md) | Directory layout, `modpack.yml`, and module inclusion. |
| Modules | [modules.md](modules.md) | Module fields, examples, ordering declarations, and parsing diagnostics. |
| Mod references | [references.md](references.md) | `wid`, `pid`, `loc`, and the future `als` reference. |
| Sorting | [sorting.md](sorting.md) | Preferred order, prefix protection, and ordering constraints. |
| Global configuration (planned) | [config.md](config.md) | Settings schema, paths, defaults, validation, and discovery sources. |
| CLI (planned) | [cli.md](cli.md) | Global `--config`, configuration selection, and the setup entry point. |
| Setup (planned) | [setup.md](setup.md) | Interactive path selection, validation, reruns, review, and saving. |
| Aliases (future, out of scope) | [aliases.md](aliases.md) | Retained design for alias definitions and resolution. |

Planned global settings are specified in [config.md](config.md). Shared CLI
configuration selection is specified in [cli.md](cli.md), and the setup wizard is
specified in [setup.md](setup.md).

Documents labeled planned or future describe intended behavior, not implemented
features. Alias support remains outside the current scope.

These specifications describe product intent. Implementation guidance and
technical caveats are recorded separately in
[IMPLEMENTATION_NOTES.md](../IMPLEMENTATION_NOTES.md).
