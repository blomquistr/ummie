# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

`ummie` is a CLI tool that fills the gap left by Unity Mod Manager's missing Mac OS GUI. It installs and uninstalls mods for Unity-based games (currently targeting Pathfinder: Wrath of the Righteous) by unpacking mod zip archives into the correct directory.

## Development Setup

All commands use the project's virtual environment at `.venv/`.

```bash
# Create venv and install with dev dependencies
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Common Commands

```bash
# Run all tests
.venv/bin/pytest

# Run a single test by name
.venv/bin/pytest -k test_install_mod_flat_creates_named_folder

# Run the CLI (after install)
.venv/bin/ummie --help

# Install a mod (dry run)
.venv/bin/ummie --dest /path/to/Mods --dry-run install --zips MyMod.zip

# Uninstall a mod (dry run)
.venv/bin/ummie --dest /path/to/Mods --dry-run uninstall --mod-names MyMod
```

The mods directory can also be set via the `WRATH_MODS_DIR` environment variable to avoid passing `--dest` on every invocation.

## Architecture

All logic lives in a single module: `src/ummie/main.py`. The `cmd()` function is the CLI entry point (registered as the `ummie` script in `pyproject.toml`). Everything else is a pure function.

**Install flow:** `cmd()` → `resolve_mods_dir()` → `install_mod()` → `detect_structure()` → `derive_mod_folder_name()`

- `detect_structure(zf)` inspects the zip for `Info.json`, determines whether the layout is `flat` (files at zip root) or `nested` (files inside a single top-level folder), and reads the mod metadata.
- `derive_mod_folder_name(info, zip_filename)` picks the filesystem folder name from `Info.json`: prefers `AssemblyName` (stem only, strips `.dll`), falls back to `Id`.
- `install_mod` handles the two layouts differently: nested zips extract directly into `mods_dir` (the top-level folder already provides the mod directory); flat zips get a new `mods_dir/<mod_name>/` directory created first.

**Uninstall flow:** `cmd()` → `resolve_mods_dir()` → `uninstall_mod()` — removes the named folder with `shutil.rmtree`.

## Tests

Tests are in `tests/test_main.py`. All zip fixtures are created in-memory using `zipfile.ZipFile` + pytest's `tmp_path` fixture — no real mod files are needed. The `_make_zip` and `_info_json` helpers at the top of the test file are the primary tools for constructing test inputs.

## Adding Game Support

To support another Unity game (e.g. Pathfinder: Kingmaker, Warhammer 40K: Rogue Trader):

1. Add a new `DEFAULT_MODS_DIR` constant for the game's expected mods path.
2. Add a `--game` flag (or a new subcommand) to `cmd()` that selects which directory constant to use as the fallback hint in the `resolve_mods_dir` error message.
3. The install/uninstall logic itself is game-agnostic — it depends only on the Unity Mod Manager `Info.json` convention, which all supported games share.
