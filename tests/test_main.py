import io
import json
import zipfile
from pathlib import Path

import pytest

import urllib.request
import zipfile as _zipfile_mod

import ummie.main as _main
from ummie.main import (
    configure_params_xml,
    derive_mod_folder_name,
    detect_structure,
    install_mod,
    resolve_mods_dir,
    uninstall_mod,
    update_harmony_dll,
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
    assert resolve_mods_dir("/from/arg", "wrath") == Path("/from/arg")


def test_resolve_mods_dir_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WRATH_MODS_DIR", "/from/env")
    assert resolve_mods_dir(None, "wrath") == Path("/from/env")


def test_resolve_mods_dir_raises_without_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WRATH_MODS_DIR", raising=False)
    with pytest.raises(SystemExit):
        resolve_mods_dir(None, "wrath")


def test_resolve_mods_dir_rogue_trader_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROGUE_TRADER_MODS_DIR", "/rt/mods")
    assert resolve_mods_dir(None, "rogue-trader") == Path("/rt/mods")


def test_resolve_mods_dir_rogue_trader_default_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROGUE_TRADER_MODS_DIR", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        resolve_mods_dir(None, "rogue-trader")
    assert "ROGUE_TRADER_MODS_DIR" in str(exc_info.value)
    assert "com.Owlcat-Games.Warhammer-40000-Rogue-Trader" in str(exc_info.value)


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


# ── configure_params_xml ──────────────────────────────────────────────────────


def _write_params_xml(path: Path, key_code: str, modifiers: str = "0") -> None:
    path.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f"<Param>"
        f"<Hotkey><keyCode>{key_code}</keyCode><modifiers>{modifiers}</modifiers></Hotkey>"
        f"</Param>",
        encoding="utf-8",
    )


def test_configure_params_xml_updates_none_keycode(tmp_path: Path) -> None:
    _write_params_xml(tmp_path / "Params.xml", "None")
    configure_params_xml(tmp_path, dry_run=False)
    import xml.etree.ElementTree as ET
    tree = ET.parse(tmp_path / "Params.xml")
    assert tree.getroot().findtext("./Hotkey/keyCode") == "F10"
    assert tree.getroot().findtext("./Hotkey/modifiers") == "2"


def test_configure_params_xml_skips_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_params_xml(tmp_path / "Params.xml", "F10", "2")
    mtime_before = (tmp_path / "Params.xml").stat().st_mtime
    configure_params_xml(tmp_path, dry_run=False)
    assert (tmp_path / "Params.xml").stat().st_mtime == mtime_before
    assert "No change" in capsys.readouterr().out


def test_configure_params_xml_creates_missing_file(tmp_path: Path) -> None:
    configure_params_xml(tmp_path, dry_run=False)
    import xml.etree.ElementTree as ET
    tree = ET.parse(tmp_path / "Params.xml")
    assert tree.getroot().findtext("./Hotkey/keyCode") == "F10"


def test_configure_params_xml_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_params_xml(tmp_path / "Params.xml", "None")
    configure_params_xml(tmp_path, dry_run=True)
    assert "[dry-run]" in capsys.readouterr().out
    import xml.etree.ElementTree as ET
    tree = ET.parse(tmp_path / "Params.xml")
    assert tree.getroot().findtext("./Hotkey/keyCode") == "None"


# ── update_harmony_dll ────────────────────────────────────────────────────────


def _make_harmony_zip(dll_bytes: bytes) -> bytes:
    """Build a minimal Harmony-Fat zip with net472/0Harmony.dll."""
    buf = io.BytesIO()
    with _zipfile_mod.ZipFile(buf, "w") as zf:
        zf.writestr("net472/0Harmony.dll", dll_bytes)
    return buf.getvalue()


def _setup_game_dir(base: Path, dll_bytes: bytes) -> Path:
    """Create a fake game app bundle with a 0Harmony.dll."""
    managed = base / "Contents" / "Resources" / "Data" / "Managed"
    managed.mkdir(parents=True)
    (managed / "0Harmony.dll").write_bytes(dll_bytes)
    return base


def test_update_harmony_dll_missing_target(tmp_path: Path) -> None:
    game_dir = tmp_path / "FakeGame.app"
    game_dir.mkdir()
    with pytest.raises(SystemExit):
        update_harmony_dll(game_dir, dry_run=False)


def test_update_harmony_dll_already_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dll_bytes = b"current dll bytes"
    game_dir = _setup_game_dir(tmp_path / "WH40KRT.app", dll_bytes)
    zip_bytes = _make_harmony_zip(dll_bytes)

    class FakeResp:
        def __init__(self, data: bytes) -> None:
            self._data = data
        def read(self) -> bytes:
            return self._data
        def __enter__(self) -> "FakeResp":
            return self
        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(
        _main, "_fetch_harmony_release", lambda: ("2.4.2.0", "http://fake/harmony.zip")
    )
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url: FakeResp(zip_bytes)
    )

    update_harmony_dll(game_dir, dry_run=False)
    assert "already up to date" in capsys.readouterr().out


def test_update_harmony_dll_replaces_outdated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_dll = b"old dll bytes"
    new_dll = b"new dll bytes"
    game_dir = _setup_game_dir(tmp_path / "WH40KRT.app", old_dll)
    zip_bytes = _make_harmony_zip(new_dll)

    class FakeResp:
        def __init__(self, data: bytes) -> None:
            self._data = data
        def read(self) -> bytes:
            return self._data
        def __enter__(self) -> "FakeResp":
            return self
        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(
        _main, "_fetch_harmony_release", lambda: ("2.5.0.0", "http://fake/harmony.zip")
    )
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url: FakeResp(zip_bytes)
    )

    update_harmony_dll(game_dir, dry_run=False)
    target = game_dir / "Contents" / "Resources" / "Data" / "Managed" / "0Harmony.dll"
    assert target.read_bytes() == new_dll


def test_update_harmony_dll_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old_dll = b"old dll bytes"
    new_dll = b"new dll bytes"
    game_dir = _setup_game_dir(tmp_path / "WH40KRT.app", old_dll)
    zip_bytes = _make_harmony_zip(new_dll)

    class FakeResp:
        def __init__(self, data: bytes) -> None:
            self._data = data
        def read(self) -> bytes:
            return self._data
        def __enter__(self) -> "FakeResp":
            return self
        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(
        _main, "_fetch_harmony_release", lambda: ("2.5.0.0", "http://fake/harmony.zip")
    )
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url: FakeResp(zip_bytes)
    )

    update_harmony_dll(game_dir, dry_run=True)
    assert "[dry-run]" in capsys.readouterr().out
    target = game_dir / "Contents" / "Resources" / "Data" / "Managed" / "0Harmony.dll"
    assert target.read_bytes() == old_dll
