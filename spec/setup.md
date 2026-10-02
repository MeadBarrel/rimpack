# Setup

Shared configuration selection is specified in [cli.md](cli.md); settings fields,
defaults, and path resolution are specified in [config.md](config.md).

## Purpose and scope

Setup is a focused, rerunnable wizard for configuring:

- `rimworld_path`: required when setup completes.
- `workshop_path`: optional, with an explicit choice to leave it unconfigured or
  clear an existing value.

Setup does not edit `data_path`, `mods_path`, or `extra_mod_paths`. Their existing
values remain unchanged. Data and Mods continue to derive from the installation
unless explicit overrides exist; setup does not write derived paths as overrides.

Setup does not install RimWorld, download mods, or modify game or mod folders.
Setup-owned filesystem changes are limited to saving the selected settings file
and creating its configuration directory when needed. Separately, CLI managed
logging may create `~/.rimpack/logs/rimpack.log` on the first emitted log record;
this does not require setup confirmation.

## Configuration selection

Setup uses the same [configuration selection rules](cli.md#config-selection) as
other commands. An override writes only to the selected location, never to the
default settings file as well.

Setup may create a missing selected settings file, including one explicitly
selected through `--config`. It begins with schema defaults when that file is
missing.

An existing file must load successfully before setup proceeds. Unreadable files,
invalid YAML, and invalid recognized values are errors, not permission to replace
or repair the file. Unknown fields produce the usual warnings but must be
preserved when saving.

Merely loading settings never starts setup or installation discovery.

## Interactive flow

The wizard:

1. Loads the selected configuration and explicitly discovers installation
   candidates.
2. Presents installation choices, including keeping the current value when
   configured and entering a path manually.
3. Presents Workshop choices, including keeping the current value when
   configured, any relevant discovered suggestion, manual entry, and no Workshop
   source.
4. Checks the proposed paths and obtains explicit acknowledgement of any
   overridden filesystem or installation-layout warnings.
5. Shows a final summary and asks for confirmation before saving.

Exact prompt wording and terminal presentation are not prescribed, but the
choices, defaults, resolved paths, and save destination must be clear.

### Installation selection

Current configured values are defaults, not automatically replaced by discovery.
The current installation remains a choice even when discovery does not find it.
Unavailable current paths receive the same checks as other proposed paths.

Discovered candidates are presented for user selection. A single candidate is
still offered for confirmation rather than silently saved. With multiple
candidates, Rimpack must not arbitrarily select an installation based on discovery
order.

Manual entry is always available, including when discovery is unsupported or
finds no candidates. Finding no candidates does not imply that RimWorld is not
installed and does not prevent manual setup.

The wizard cannot complete with `rimworld_path` unset. An existing installation
path may be retained or replaced, but setup does not offer to clear it.

### Workshop selection

A discovered Workshop folder associated with the selected installation is a
suggestion, not a mandatory pairing. The user may choose a different folder or
no Workshop source.

On reruns, the current Workshop value remains the default even if the installation
changes. Setup must not silently replace or clear it. Both proposed paths appear
in the final summary so the user can review their combination.

Selecting no Workshop source removes an existing `workshop_path` field or leaves
it absent in a new configuration. It never writes a blank value or empty string.
An empty but accessible Workshop directory is a valid source; subscribed mods
are not required to complete setup.

## Manual path entry

For a path entered into the wizard:

1. Expand a leading `~` referring to the current user's home directory.
2. Anchor relative input to the command's current working directory.
3. Show and save the resulting absolute path.

These are prompt-input rules, not a change to YAML path resolution. Existing
relative settings are still resolved against the selected settings file's
directory. Keeping an existing value does not reinterpret it relative to the
working directory or rewrite its spelling.

Environment-variable expressions are not expanded by Rimpack. Manual input follows
[the settings path-value requirements](config.md#path-values-and-resolution):
nonempty, non-whitespace, no NUL, with meaningful spaces preserved and host-platform
path syntax. Invalid path values are errors and cannot be accepted by overriding a
warning. Clearing Workshop is a separate explicit choice, not blank path input.

## Path checks and warning overrides

Before saving, setup checks whether each configured proposed path is an accessible
directory. It also performs a best-effort check that the installation path looks
like a RimWorld installation root, rather than an executable or a content
subdirectory.

Missing or inaccessible directories, non-directory targets, and an unrecognized
installation layout produce warnings identifying the path and concern. These
filesystem and layout warnings may be overridden explicitly so unavailable drives
and unusual installations remain configurable. Merely choosing a path does not
acknowledge its warnings, and ordinary save confirmation must not silently waive
them.

Warnings do not cause Rimpack to substitute another path. An acknowledged warning
also does not change how future commands handle unavailable discovery sources.

These checks are additional setup feedback. Normal configuration loading retains
its existing separation between schema validation and filesystem availability.

## Final review and saving

The final summary shows:

- The absolute location of the selected settings file.
- Current and proposed installation and Workshop values, identifying changes and
  an unconfigured Workshop source explicitly.
- The effective Data and Mods paths under the proposed settings, distinguishing
  explicit overrides from installation-derived defaults.
- Any acknowledged path warnings.

The user must confirm the save. Until confirmation, setup must not write the
settings file or create missing configuration directories. Declining confirmation
or cancelling the wizard leaves the file and directories unchanged.

Saving changes only the two managed fields. Other recognized fields, unknown
fields, and unrelated comments and formatting must be preserved. Retained values
must not be normalized or reformatted merely because setup was run. If the user
makes no changes to an existing configuration, do not rewrite the file; report
that no changes were needed.

A save failure is an error, not successful setup. On success, report the selected
settings-file location and whether it was saved or unchanged.

## Noninteractive use

The initial command is interactive-only. It does not provide noninteractive path
options or a flag to accept all prompts or warnings.

Without usable terminal input, report an actionable error and make no filesystem
changes. Explain that the user can run setup interactively or create the selected
settings YAML directly. Other commands continue to support manually configured
settings without requiring setup.
