import json
import zipfile
from pathlib import Path

import pytest

from ummie.main import (
    derive_mod_folder_name,
    detect_structure,
    install_mod,
    resolve_mods_dir,
    uninstall_mod,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_zip(entries: dict[str, str | bytes], path: Path) -> Path:
    """Write a zip archive to *path* with the given name→content mapping."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            data = content if isinstance(content, bytes) else content.encode()
            zf.writestr(name, data)
    return path


def _info_json(assembly: str | None = "MyMod.dll", mod_id: str | None = "MyMod") -> str:
    """Build a minimal Info.json payload; omit keys whose value is None."""
    info: dict[str, str] = {}
    if assembly is not None:
        info["AssemblyName"] = assembly
    if mod_id is not None:
        info["Id"] = mod_id
    return json.dumps(info)


# ── resolve_mods_dir ──────────────────────────────────────────────────────────


def test_resolve_mods_dir_arg_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WRATH_MODS_DIR", "/from/env")
    assert resolve_mods_dir("/from/arg") == Path("/from/arg")


def test_resolve_mods_dir_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WRATH_MODS_DIR", "/from/env")
    assert resolve_mods_dir(None) == Path("/from/env")


def test_resolve_mods_dir_raises_without_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WRATH_MODS_DIR", raising=False)
    with pytest.raises(SystemExit):
        resolve_mods_dir(None)


# ── derive_mod_folder_name ────────────────────────────────────────────────────


def test_derive_folder_name_uses_assembly_stem() -> None:
    assert derive_mod_folder_name({"AssemblyName": "MyMod.dll"}, "MyMod.zip") == "MyMod"


def test_derive_folder_name_assembly_without_extension() -> None:
    assert derive_mod_folder_name({"AssemblyName": "MyMod"}, "MyMod.zip") == "MyMod"


def test_derive_folder_name_falls_back_to_id() -> None:
    assert derive_mod_folder_name({"Id": "MyMod"}, "MyMod.zip") == "MyMod"


def test_derive_folder_name_unusual_id_emits_warning(capsys: pytest.CaptureFixture[str]) -> None:
    result = derive_mod_folder_name({"Id": "1BadId"}, "weird.zip")
    assert result == "1BadId"
    assert "Warning" in capsys.readouterr().err


def test_derive_folder_name_raises_on_empty_info() -> None:
    with pytest.raises(SystemExit):
        derive_mod_folder_name({}, "missing.zip")


# ── detect_structure ──────────────────────────────────────────────────────────


def test_detect_structure_flat(tmp_path: Path) -> None:
    zp = _make_zip({"Info.json": _info_json(), "MyMod.dll": b""}, tmp_path / "mod.zip")
    with zipfile.ZipFile(zp) as zf:
        name, structure = detect_structure(zf)
    assert structure == "flat"
    assert name == "MyMod"


def test_detect_structure_nested(tmp_path: Path) -> None:
    zp = _make_zip(
        {"MyMod/Info.json": _info_json(), "MyMod/MyMod.dll": b""},
        tmp_path / "mod.zip",
    )
    with zipfile.ZipFile(zp) as zf:
        name, structure = detect_structure(zf)
    assert structure == "nested"
    assert name == "MyMod"


def test_detect_structure_raises_on_missing_info_json(tmp_path: Path) -> None:
    zp = _make_zip({"MyMod.dll": b""}, tmp_path / "mod.zip")
    with zipfile.ZipFile(zp) as zf:
        with pytest.raises(SystemExit):
            detect_structure(zf)


def test_detect_structure_raises_on_multiple_info_json(tmp_path: Path) -> None:
    zp = _make_zip(
        {
            "ModA/Info.json": _info_json(assembly="ModA.dll", mod_id="ModA"),
            "ModB/Info.json": _info_json(assembly="ModB.dll", mod_id="ModB"),
        },
        tmp_path / "multi.zip",
    )
    with zipfile.ZipFile(zp) as zf:
        with pytest.raises(SystemExit):
            detect_structure(zf)


def test_detect_structure_raises_on_deeply_nested(tmp_path: Path) -> None:
    zp = _make_zip({"outer/inner/Info.json": _info_json()}, tmp_path / "deep.zip")
    with zipfile.ZipFile(zp) as zf:
        with pytest.raises(SystemExit):
            detect_structure(zf)


# ── install_mod ───────────────────────────────────────────────────────────────


def test_install_mod_raises_on_missing_zip(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        install_mod(tmp_path / "nonexistent.zip", tmp_path / "Mods", dry_run=False)


def test_install_mod_raises_on_invalid_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(SystemExit):
        install_mod(bad, tmp_path / "Mods", dry_run=False)


def test_install_mod_dry_run_flat_prints_and_skips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    zp = _make_zip({"Info.json": _info_json(), "MyMod.dll": b""}, tmp_path / "mod.zip")
    mods_dir = tmp_path / "Mods"
    install_mod(zp, mods_dir, dry_run=True)
    assert "[dry-run]" in capsys.readouterr().out
    assert not mods_dir.exists()


def test_install_mod_dry_run_nested_prints_and_skips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    zp = _make_zip(
        {"MyMod/Info.json": _info_json(), "MyMod/MyMod.dll": b""},
        tmp_path / "mod.zip",
    )
    mods_dir = tmp_path / "Mods"
    install_mod(zp, mods_dir, dry_run=True)
    assert "[dry-run]" in capsys.readouterr().out
    assert not mods_dir.exists()


def test_install_mod_flat_creates_named_folder(tmp_path: Path) -> None:
    zp = _make_zip(
        {"Info.json": _info_json(), "MyMod.dll": b"dlbytes"},
        tmp_path / "mod.zip",
    )
    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    install_mod(zp, mods_dir, dry_run=False)
    assert (mods_dir / "MyMod" / "Info.json").exists()
    assert (mods_dir / "MyMod" / "MyMod.dll").exists()


def test_install_mod_nested_extracts_into_mods_dir(tmp_path: Path) -> None:
    zp = _make_zip(
        {"MyMod/Info.json": _info_json(), "MyMod/MyMod.dll": b"dlbytes"},
        tmp_path / "mod.zip",
    )
    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    install_mod(zp, mods_dir, dry_run=False)
    assert (mods_dir / "MyMod" / "Info.json").exists()
    assert (mods_dir / "MyMod" / "MyMod.dll").exists()


# ── uninstall_mod ─────────────────────────────────────────────────────────────


def test_uninstall_mod_raises_on_missing_mod(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        uninstall_mod("NonExistent", tmp_path, dry_run=False)


def test_uninstall_mod_raises_when_target_is_file(tmp_path: Path) -> None:
    (tmp_path / "MyMod").write_text("oops")
    with pytest.raises(SystemExit):
        uninstall_mod("MyMod", tmp_path, dry_run=False)


def test_uninstall_mod_dry_run_prints_and_keeps_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod_dir = tmp_path / "MyMod"
    mod_dir.mkdir()
    uninstall_mod("MyMod", tmp_path, dry_run=True)
    assert "[dry-run]" in capsys.readouterr().out
    assert mod_dir.exists()


def test_uninstall_mod_removes_folder(tmp_path: Path) -> None:
    mod_dir = tmp_path / "MyMod"
    mod_dir.mkdir()
    (mod_dir / "MyMod.dll").write_bytes(b"")
    uninstall_mod("MyMod", tmp_path, dry_run=False)
    assert not mod_dir.exists()
