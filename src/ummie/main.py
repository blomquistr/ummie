import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

# For MVP1, this is not a fallback; this constant is for
# informational purposes only to tell a user other than
# me where to look for their mods dir (also to remind me
# when I inevitably forget)
DEFAULT_MODS_DIR = "/Applications/Pathfinder Wrath of the Righteous/Mods"


def resolve_mods_dir(dest_arg: str | None) -> Path:
    """Resolve the mods directory from CLI arg, environment, or raise."""
    if dest_arg:
        return Path(dest_arg)
    from_env = os.getenv("WRATH_MODS_DIR")
    if from_env:
        return Path(from_env)
    raise SystemExit(
        "Error: no mods directory specified.\n"
        "Use --dest <path> or set the WRATH_MODS_DIR environment variable.\n"
        f"Default expected path: {DEFAULT_MODS_DIR}"
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


def cmd() -> None:
    parser = argparse.ArgumentParser(
        prog="ummie",
        description="Install and uninstall Wrath of the Righteous mods.",
    )
    parser.add_argument(
        "--dest",
        metavar="PATH",
        help="Mods directory. Overrides WRATH_MODS_DIR env var.",
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

    args = parser.parse_args()
    mods_dir = resolve_mods_dir(args.dest)

    errors = []

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

    if errors:
        print(file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)
