from keiltool.core.tool_finder import find_openocd_scripts


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
