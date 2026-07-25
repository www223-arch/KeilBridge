from pathlib import Path

from keiltool.core.keil_cli import build_keil_command, find_keil_batch, _log_has_keil_errors, _replace_missing_armcc_paths


def test_build_keil_command_uses_target_and_output_log(tmp_path):
    project = tmp_path / "motor.uvprojx"
    project.write_text("<Project />", encoding="utf-8")
    log = tmp_path / "build.log"

    command = build_keil_command("UV4.exe", project, "Target 1", "build", log)

    assert command[0] == "UV4.exe"
    assert command[1] == "-b"
    assert command[2] == str(project.resolve())
    assert command[3] == "-tTarget 1"
    assert command[4] == f"-o{log.resolve()}"


def test_download_keil_command_uses_flash_switch(tmp_path):
    project = tmp_path / "motor.uvprojx"
    project.write_text("<Project />", encoding="utf-8")

    command = build_keil_command("UV4.exe", project, None, "download", tmp_path / "download.log")

    assert command[1] == "-f"
    assert not any(item.startswith("-t") for item in command)


def test_find_keil_batch_prefers_target_named_batch(tmp_path):
    project = tmp_path / "motor.uvprojx"
    project.write_text("<Project />", encoding="utf-8")
    fallback = tmp_path / "Other.BAT"
    preferred = tmp_path / "Target 1.BAT"
    fallback.write_text("echo other\n", encoding="utf-8")
    preferred.write_text("echo target\n", encoding="utf-8")

    assert find_keil_batch(project, "Target 1") == preferred


def test_replace_missing_armcc_paths_updates_only_missing_tool_roots(tmp_path):
    replacement = tmp_path / "ARMCC" / "bin"
    replacement.mkdir(parents=True)
    (replacement / "armcc.exe").write_text("", encoding="utf-8")
    text = r'"D:\Keil_v5\ARM\ARMCC\Bin\ArmCC" --Via "..\output\main.__i"'

    patched = _replace_missing_armcc_paths(text, replacement)

    assert str(replacement) in patched
    assert r"D:\Keil_v5\ARM\ARMCC\Bin" not in patched


def test_log_has_keil_errors_detects_fatal_even_when_batch_returncode_is_zero(tmp_path):
    log = tmp_path / "keil.log"
    log.write_text("Fatal error: C3904U: Could not open via file '..\\output\\main.__i'.\n", encoding="utf-8")

    assert _log_has_keil_errors(log)
