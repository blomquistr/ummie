import argparse
import os
import sys
import zipfile
from pathlib import Path

# For MVP1, this is not a fallback; this constant is for
# informational purposes only to tell a user other than
# me where to look for their mods dir (also to remind me
# when I inevitably forget)
DEFAULT_MODS_DIR = (
    "/Applications/Pathfinder Wrath of the Righteous/"
    "Wrath.app/Contents/Resources/Data/Mods"
)


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


def install_mod(zip_path: Path, mods_dir: Path, dry_run: bool) -> None:
    """Extract a single mod zip into mods_dir."""
    if not zip_path.exists():
        raise SystemExit(f"Error: zip file not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise SystemExit(f"Error: not a valid zip file: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        top_level = {Path(name).parts[0] for name in zf.namelist()}
        if len(top_level) != 1:
            raise SystemExit(
                f"Warning: '{zip_path.name}' has an unexpected structure "
                f"(top-level entries: {sorted(top_level)}). "
                "Refusing to extract — inspect manually."
            )
        mod_name = next(iter(top_level))
        dest = mods_dir / mod_name

        if dry_run:
            print(f"[dry-run] Would extract '{zip_path.name}' -> {dest}")
            return

        print(f"Installing '{mod_name}' -> {dest}")
        mods_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(mods_dir)
        print(f"  Done.")


def cmd() -> None:
    parser = argparse.ArgumentParser(
        prog="ummie",
        description="Install Wrath of the Righteous mods from zip files.",
    )
    parser.add_argument(
        "--zips",
        nargs="+",
        metavar="ZIP",
        help="One or more mod zip files to install.",
    )
    parser.add_argument(
        "--dest",
        metavar="PATH",
        help="Mods directory. Overrides WRATH_MODS_DIR env var.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be installed without extracting anything.",
    )

    args = parser.parse_args()
    mods_dir = resolve_mods_dir(args.dest)

    errors = []
    for zip_arg in args.zips:
        try:
            install_mod(Path(zip_arg), mods_dir, dry_run=args.dry_run)
        except SystemExit as e:
            errors.append(str(e))

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)

