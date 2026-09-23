import sys

from keiltool.core.tool_finder import find_openocd, find_openocd_scripts


def test_find_openocd_scripts_supports_share_layout(tmp_path):
    root = tmp_path / "openocd"
    executable = root / "bin" / "openocd.exe"
    scripts = root / "share" / "openocd" / "scripts"
    executable.parent.mkdir(parents=True)
    scripts.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")

    assert find_openocd_scripts(str(executable)) == str(scripts)


def test_find_openocd_scripts_supports_xpack_layout(tmp_path):
    root = tmp_path / "xpack-openocd-0.12.0-7"
    executable = root / "bin" / "openocd.exe"
    scripts = root / "openocd" / "scripts"
    executable.parent.mkdir(parents=True)
    scripts.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")

    assert find_openocd_scripts(str(executable)) == str(scripts)


def test_find_openocd_prefers_the_portable_bundle(monkeypatch, tmp_path):
    executable = tmp_path / "openocd" / "bin" / "openocd.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    monkeypatch.setenv("KEILTOOL_PORTABLE_ROOT", str(tmp_path))
    monkeypatch.setattr("keiltool.core.tool_finder.shutil.which", lambda _name: "C:/other/openocd.exe")

    assert find_openocd() == str(executable)


def test_find_openocd_scripts_supports_portable_layout(tmp_path):
    executable = tmp_path / "openocd" / "bin" / "openocd.exe"
    scripts = tmp_path / "openocd" / "scripts"
    executable.parent.mkdir(parents=True)
    scripts.mkdir(parents=True)
    executable.write_bytes(b"MZ")

    assert find_openocd_scripts(str(executable)) == str(scripts)


def test_find_openocd_uses_one_file_extraction_root(monkeypatch, tmp_path):
    executable = tmp_path / "openocd" / "bin" / "openocd.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    monkeypatch.delenv("KEILTOOL_PORTABLE_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "outside" / "RTT-Collector.exe"))
    monkeypatch.setattr("keiltool.core.tool_finder.shutil.which", lambda _name: None)

    assert find_openocd() == str(executable)
