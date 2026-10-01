## Setup the CLI

Run the interactive setup wizard in a terminal to choose the RimWorld installation
and optional Workshop content folder:

```sh
rimpack setup
```

Select an alternate settings file or directory with the global `--config` option
before the command:

```sh
rimpack --config ~/profiles/testing/settings.yaml setup
```

The wizard checks the selected paths, reviews effective Data and Mods locations,
and asks before saving. It does not install or modify game or mod files.

## SDK configuration

```python
from rimpack.sdk.config import load_config
from rimpack.sdk.diagnostics import render_diagnostics

result = load_config()  # ~/.rimpack/settings.yml; absent default means empty settings
# Or load_config("profiles/testing/settings.yaml") to select another file.
print(result.value.effective_data_path)  # explicit override or rimworld_path / "Data"
print(result.value.effective_mods_path)  # explicit override or rimworld_path / "Mods"
if result.diagnostics:
    print(render_diagnostics(result.diagnostics))  # ignored unknown settings keys
```

Paths in YAML are relative to the selected file's directory. The SDK returns
warnings rather than emitting them and does not create files or discover mods.
The interactive setup command is available through `rimpack setup`.

## Development

Install the development tools and set up the Git hooks:

```sh
uv sync
uv run prek install
```

Run all hooks manually with:

```sh
uv run prek run --all-files
```
