# Command-line interface

This specification describes planned shared CLI configuration behavior and the
setup command entry point. These CLI features are not yet implemented; the SDK
settings loader implements the selection and missing-file rules below. Settings
fields, defaults, and discovery-source behavior are specified in
[config.md](config.md). The interactive setup contract is specified in
[setup.md](setup.md).

## Global configuration option

Every command uses the same global optional `--config PATH` option:

```text
rimpack [--config PATH] <command> [command arguments and options]
```

`--config` must appear before the subcommand. It is not a command-local option.
For example:

```text
rimpack setup
rimpack --config ./alternate/.rimpack setup
rimpack --config ./alternate/custom.yaml setup
```

The form `rimpack setup --config PATH` is not supported. The global placement
rule applies to every command, including commands introduced later.

## Config selection

Without `--config`, select `~/.rimpack/settings.yml`.

When `--config PATH` is present, Rimpack expands a leading `~` referring to the
current user's home directory. Relative arguments are resolved against the
command's current working directory, not against the default configuration
folder. Rimpack does not expand environment-variable expressions; any expansion
performed by the shell happens before Rimpack receives the argument.
On Windows, drive-relative arguments such as `C:settings.yml` are rejected;
use `C:/settings.yml` for an absolute path or `settings.yml` for a path relative
to the working directory.

After resolving the argument, select the settings file as follows:

| Target | Selected settings file |
| --- | --- |
| Existing directory | `settings.yml` inside that directory |
| Existing file | That exact file, read as YAML regardless of its extension |
| Nonexistent path ending in `.yml` or `.yaml` | That exact path |
| Any other nonexistent path | `settings.yml` inside that path |

Existing filesystem type takes precedence over the extension hint. For example,
an existing directory named `profile.yaml` selects `profile.yaml/settings.yml`.
The selected configuration directory does not have to be named `.rimpack`.

Only the selected settings file is loaded. An alternative configuration
completely replaces the default configuration: there is no merging with or
fallback to `~/.rimpack/settings.yml`. Fields omitted from the selected file use
the [schema defaults](config.md#schema), not values from the default file.

Paths inside the selected settings file are relative to that file's directory,
as specified in [config.md](config.md#path-values-and-resolution). This is distinct
from resolving a relative `--config` argument against the working directory.

## Missing configuration

For commands other than setup:

- If `--config` is absent and the default settings file does not exist, use empty
  settings with schema defaults. Do not create the file merely by reading it.
- If `--config` explicitly selects a missing settings file, report an error. This
  also applies when the selected folder exists but its `settings.yml` is absent.
- An existing unreadable or invalid configuration is an error, whether it is the
  default or an explicit selection. Do not treat it as absent or try another file.

`setup` may create a missing configuration at the selected location, including
one explicitly selected through `--config`.

An unset path does not implicitly request installation discovery. A command that
requires an unconfigured path must report that configuration is needed rather
than silently choosing an installation.

## Setup

The explicit configuration setup action is:

```text
rimpack setup
```

Setup is an interactive, rerunnable wizard for a required RimWorld installation
path and an optional Workshop path. It uses the same configuration selection
rules as every other command, explicitly discovers candidates, and supports
manual path entry. Existing values are defaults; discovery does not silently
replace them or arbitrarily choose among multiple candidates.

The user confirms a final summary before setup saves the selected paths. Setup
may create the selected configuration directory and file when needed, but makes
no filesystem changes before confirmation. It preserves unrelated settings and
content. The full selection, validation, cancellation, and saving contract is
specified in [setup.md](setup.md).

To set up an independent configuration:

```text
rimpack --config ~/profiles/testing/.rimpack setup
rimpack --config ~/profiles/testing/settings.yaml setup
```

Setup with an override writes to the selected location, not the default location.
Merely loading settings never invokes setup or installation discovery.

Initial setup is interactive-only; without usable terminal input it reports an
error and makes no filesystem changes. Exact prompt wording is not prescribed.

## Diagnostics

Configuration warnings and errors follow [config.md](config.md#loading-and-validation):
unknown fields are reported and ignored, while malformed recognized values and
configuration read failures are errors.

During mod discovery, unavailable source folders are reported as warnings and
skipped, as specified in [config.md](config.md#mod-discovery-sources). Those
warnings alone do not make discovery fail; other errors, such as configuration
validation failures, remain errors.
