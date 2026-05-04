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

The mods directory can also be set via the game-specific env var (e.g. `WRATH_MODS_DIR`) to avoid passing `--dest` on every invocation. The active game can be set via `UMMIE_GAME` to avoid passing `--game`.

## Architecture

Logic is split across two modules:

- **`src/ummie/config.py`** — `GameConfig` and `Config` dataclasses, built-in game defaults, TOML config loading (`load_config`), and game/config-path resolution (`resolve_game`).
- **`src/ummie/main.py`** — all mod operations as pure functions; `cmd()` is the CLI entry point registered in `pyproject.toml`.

**Config resolution order** (highest priority first):

| Setting | CLI flag | Env var | Config file | Hardcoded default |
|---|---|---|---|---|
| Config file path | `--config` | `UMMIE_CONFIG` | — | `~/.config/ummie/config.toml` |
| Active game | `--game` | `UMMIE_GAME` | `default_game` | `wrath` |
| Mods directory | `--dest` | per-game `env_var` | — | error with hint |

**Install flow:** `cmd()` → `load_config()` → `resolve_game()` → `resolve_mods_dir()` → `install_mod()` → `detect_structure()` → `derive_mod_folder_name()`

- `detect_structure(zf)` inspects the zip for `Info.json`, determines whether the layout is `flat` (files at zip root) or `nested` (files inside a single top-level folder), and reads the mod metadata.
- `derive_mod_folder_name(info, zip_filename)` picks the filesystem folder name from `Info.json`: prefers `AssemblyName` (stem only, strips `.dll`), falls back to `Id`.
- `install_mod` handles the two layouts differently: nested zips extract directly into `mods_dir` (the top-level folder already provides the mod directory); flat zips get a new `mods_dir/<mod_name>/` directory created first.

**Uninstall flow:** `cmd()` → `resolve_mods_dir()` → `uninstall_mod()` — removes the named folder with `shutil.rmtree`.

## Config File Format

The optional TOML config at `~/.config/ummie/config.toml` (or `UMMIE_CONFIG`) looks like:

```toml
default_game = "wrath"

[games.wrath]
env_var = "WRATH_MODS_DIR"
default_mods_dir = "/Applications/Pathfinder Wrath of the Righteous/Mods"

[games.rogue-trader]
env_var = "ROGUE_TRADER_MODS_DIR"
default_mods_dir = "~/Library/Application Support/com.Owlcat-Games.Warhammer-40000-Rogue-Trader/UnityModManager"
game_dir = "/Applications/Warhammer 40,000 Rogue Trader/WH40KRT.app"
```

If the file is absent or contains no `[games]` section, the built-in defaults from `config.py` are used.

## Tests

Tests are in `tests/test_main.py`. All zip fixtures are created in-memory using `zipfile.ZipFile` + pytest's `tmp_path` fixture — no real mod files are needed. The `_make_zip` and `_info_json` helpers at the top of the test file are the primary tools for constructing test inputs.

## Adding Game Support

To support another Unity game, add a new `GameConfig` entry to `_DEFAULT_GAMES` in `src/ummie/config.py`:

```python
"my-game": GameConfig(
    env_var="MY_GAME_MODS_DIR",
    default_mods_dir="/Applications/My Game/Mods",
    game_dir=None,  # set if the game needs the setup subcommand
),
```

No changes to `main.py` are needed — the install/uninstall logic is game-agnostic and depends only on the Unity Mod Manager `Info.json` convention. Users can also add games via a config file without touching the code.
