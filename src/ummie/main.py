import argparse
import io
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from ummie.config import Config, GameConfig, load_config, resolve_game


HARMONY_DLL_NET_TARGET = "net472"
HARMONY_GITHUB_API = "https://api.github.com/repos/pardeike/Harmony/releases/latest"


def resolve_mods_dir(dest_arg: str | None, game_config: GameConfig) -> Path:
    """Resolve the mods directory from CLI arg, environment, or raise."""
    if dest_arg:
        return Path(dest_arg)
    from_env = os.getenv(game_config.env_var)
    if from_env:
        return Path(from_env)
    raise SystemExit(
        f"Error: no mods directory specified.\n"
        f"Use --dest <path> or set the {game_config.env_var} environment variable.\n"
        f"Default expected path: {game_config.default_mods_dir}"
    )


def derive_mod_folder_name(info: dict, zip_filename: str) -> str:
    """Derive a filesystem-safe folder name from Info.json contents.

    Prefers AssemblyName (stem) as the most reliable filesystem-safe identifier.
    Falls back to Id unmodified, with a warning if it looks unusual.
    Raises SystemExit if neither field yields a usable name.
    """
    if assembly := info.get("AssemblyName"):
        return Path(assembly).stem

    if mod_id := info.get("Id"):
        if not mod_id[0].isalpha():
            print(
                f"Warning: '{zip_filename}' has an unusual mod Id '{mod_id}'. "
                f"Installing to folder '{mod_id}' — verify this is correct.",
                file=sys.stderr,
            )
        return mod_id

    raise SystemExit(
        f"Cannot derive a folder name from Info.json in '{zip_filename}': {info}.\n"
        "Please install this mod manually."
    )


def detect_structure(zf: zipfile.ZipFile) -> tuple[str, str]:
    """Inspect a zip and return (mod_folder_name, structure).

    structure is one of:
      'nested' - mod files are inside a single top-level directory
      'flat'   - mod files are at the zip root

    Raises SystemExit for unrecognized or unsupported layouts.
    """
    info_candidates = [
        n
        for n in zf.namelist()
        if n == "Info.json" or n.endswith("/Info.json")
    ]

    if len(info_candidates) == 0:
        raise SystemExit(
            f"No Info.json found in '{zf.filename}'.\n"
            "Please install this mod manually."
        )
    if len(info_candidates) > 1:
        raise SystemExit(
            f"Multiple Info.json files found in '{zf.filename}'.\n"
            "Please install this mod manually."
        )

    info_path = info_candidates[0]
    parts = info_path.split("/")

    if len(parts) == 1:
        structure = "flat"
    elif len(parts) == 2:
        structure = "nested"
    else:
        raise SystemExit(
            f"'{zf.filename}' is nested more than one directory deep.\n"
            "Please install this mod manually."
        )

    with zf.open(info_path) as f:
        info = json.loads(f.read().decode("utf-8-sig"))

    mod_folder = derive_mod_folder_name(info, Path(zf.filename).name)
    return mod_folder, structure


def install_mod(zip_path: Path, mods_dir: Path, dry_run: bool) -> None:
    """Extract a single mod zip into mods_dir."""
    if not zip_path.exists():
        raise SystemExit(f"Error: zip file not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise SystemExit(f"Error: not a valid zip file: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        mod_folder, structure = detect_structure(zf)
        dest = mods_dir / mod_folder

        if dry_run:
            print(
                f"[dry-run] Would extract '{zip_path.name}' "
                f"({structure}) -> {dest}"
            )
            return

        print(f"Installing '{mod_folder}' -> {dest}  [{structure}]")
        if structure == "nested":
            zf.extractall(mods_dir)
        else:
            # flat: the zip has no wrapping folder, so we create it
            dest.mkdir(parents=True, exist_ok=True)
            zf.extractall(dest)
        print("  Done.")


def uninstall_mod(mod_name: str, mods_dir: Path, dry_run: bool) -> None:
    """Remove a mod folder from mods_dir by name.

    # TODO: check installed dependents before removing
    """
    import shutil

    target = mods_dir / mod_name
    if not target.exists():
        raise SystemExit(
            f"Error: no mod folder '{mod_name}' found in {mods_dir}"
        )
    if not target.is_dir():
        raise SystemExit(
            f"Error: '{target}' exists but is not a directory — refusing to remove."
        )

    if dry_run:
        print(f"[dry-run] Would remove '{target}'")
        return

    print(f"Uninstalling '{mod_name}' from {mods_dir}")
    shutil.rmtree(target)
    print("  Done.")


def configure_params_xml(mods_dir: Path, dry_run: bool) -> None:
    """Ensure Params.xml has a usable hotkey for the UMM overlay.

    The game ships with keyCode=None (no binding). This sets it to F10+Shift
    so the mod manager can be opened in-game.
    """
    params_path = mods_dir / "Params.xml"

    if not params_path.exists():
        if dry_run:
            print(f"[dry-run] Would create {params_path} with hotkey F10+Shift.")
            return
        root = ET.Element("Param")
        hotkey = ET.SubElement(root, "Hotkey")
        ET.SubElement(hotkey, "keyCode").text = "F10"
        ET.SubElement(hotkey, "modifiers").text = "2"
        params_path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
        print(f"  Created {params_path} with hotkey F10+Shift.")
        return

    tree = ET.parse(params_path)
    root = tree.getroot()
    keycode_el = root.find("./Hotkey/keyCode")

    if keycode_el is not None and keycode_el.text != "None":
        print(f"  Params.xml hotkey already configured ({keycode_el.text!r}). No change.")
        return

    current = keycode_el.text if keycode_el is not None else "(missing)"
    if dry_run:
        print(
            f"[dry-run] Would update {params_path}: "
            f"keyCode {current!r} -> 'F10', modifiers -> '2'."
        )
        return

    hotkey_el = root.find("./Hotkey")
    if hotkey_el is None:
        hotkey_el = ET.SubElement(root, "Hotkey")

    if keycode_el is None:
        keycode_el = ET.SubElement(hotkey_el, "keyCode")
    keycode_el.text = "F10"

    modifiers_el = hotkey_el.find("modifiers")
    if modifiers_el is None:
        modifiers_el = ET.SubElement(hotkey_el, "modifiers")
    modifiers_el.text = "2"

    params_path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    print(f"  Updated {params_path}: hotkey set to F10+Shift.")


def _fetch_harmony_release() -> tuple[str, str]:
    """Return (version_string, fat_zip_download_url) for the latest Harmony release."""
    with urllib.request.urlopen(HARMONY_GITHUB_API) as resp:
        release = json.loads(resp.read())
    version: str = release["tag_name"].lstrip("v")
    for asset in release["assets"]:
        name: str = asset["name"]
        if name.startswith("Harmony-Fat.") and name.endswith(".zip"):
            return version, asset["browser_download_url"]
    raise SystemExit(
        f"No Harmony-Fat zip found in release {release['tag_name']}.\n"
        "Check https://github.com/pardeike/Harmony/releases manually."
    )


def _extract_harmony_dll(zip_bytes: bytes) -> bytes:
    """Extract the net472 0Harmony.dll bytes from a Harmony-Fat zip."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return zf.read(f"{HARMONY_DLL_NET_TARGET}/0Harmony.dll")


def update_harmony_dll(game_dir: Path, dry_run: bool) -> None:
    """Replace 0Harmony.dll in the game app bundle with the latest net472 build."""
    target = game_dir / "Contents" / "Resources" / "Data" / "Managed" / "0Harmony.dll"
    if not target.exists():
        raise SystemExit(
            f"Error: 0Harmony.dll not found at {target}\n"
            "Verify --game-dir points to the WH40KRT.app bundle."
        )

    print("Checking for Harmony update...")
    version, zip_url = _fetch_harmony_release()
    print(f"  Latest Harmony release: {version}")
    with urllib.request.urlopen(zip_url) as resp:
        zip_bytes = resp.read()
    new_dll = _extract_harmony_dll(zip_bytes)

    if new_dll == target.read_bytes():
        print("  0Harmony.dll is already up to date. No change.")
        return

    if dry_run:
        print(
            f"[dry-run] Would replace {target} "
            f"with Harmony {version} ({HARMONY_DLL_NET_TARGET})."
        )
        return

    target.write_bytes(new_dll)
    print(f"  Replaced {target} with Harmony {version} ({HARMONY_DLL_NET_TARGET}). Done.")


def cmd() -> None:
    parser = argparse.ArgumentParser(
        prog="ummie",
        description="Install and uninstall mods for Unity-based games.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            f"Path to a TOML config file. "
            f"Overrides the UMMIE_CONFIG environment variable."
        ),
    )
    parser.add_argument(
        "--game",
        metavar="GAME",
        default=None,
        help=(
            "Game to manage mods for. "
            "Overrides the UMMIE_GAME environment variable and config file default."
        ),
    )
    parser.add_argument(
        "--dest",
        metavar="PATH",
        help="Mods directory. Overrides the game-specific env var.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making any changes.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser(
        "install",
        help="Install one or more mods from zip files.",
    )
    install_parser.add_argument(
        "--zips",
        nargs="+",
        metavar="ZIP",
        help="One or more mod zip files to install.",
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Uninstall a mod by folder name.",
    )
    uninstall_parser.add_argument(
        "--mod-names",
        nargs="+",
        metavar="MOD",
        help="One or more mod folder names to remove.",
    )

    setup_parser = subparsers.add_parser(
        "setup",
        help="One-time game mod setup (Params.xml hotkey + 0Harmony.dll update).",
    )
    setup_parser.add_argument(
        "--game-dir",
        metavar="PATH",
        default=None,
        help="Path to the game app bundle (default: from game config).",
    )

    args = parser.parse_args()

    config: Config = load_config(Path(args.config) if args.config else None)
    game: str = resolve_game(args.game, config)
    if game not in config.games:
        valid = ", ".join(config.games)
        sys.exit(f"Error: unknown game {game!r}. Valid games: {valid}")
    game_config: GameConfig = config.games[game]
    mods_dir = resolve_mods_dir(args.dest, game_config)

    errors: list[str] = []

    if args.command == "install":
        for zip_arg in args.zips:
            try:
                install_mod(Path(zip_arg), mods_dir, dry_run=args.dry_run)
            except SystemExit as e:
                errors.append(str(e))

    elif args.command == "uninstall":
        for mod_name in args.mod_names:
            try:
                uninstall_mod(mod_name, mods_dir, dry_run=args.dry_run)
            except SystemExit as e:
                errors.append(str(e))

    elif args.command == "setup":
        if args.game != "rogue-trader":
            sys.exit("Error: 'setup' is only supported for --game rogue-trader.")
        game_dir_str = args.game_dir or game_config.game_dir
        if game_dir_str is None:
            sys.exit(
                "Error: --game-dir required (no default game_dir configured for this game)."
            )
        try:
            configure_params_xml(mods_dir, dry_run=args.dry_run)
        except SystemExit as e:
            errors.append(str(e))
        try:
            update_harmony_dll(Path(game_dir_str), dry_run=args.dry_run)
        except SystemExit as e:
            errors.append(str(e))

    if errors:
        print(file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)
