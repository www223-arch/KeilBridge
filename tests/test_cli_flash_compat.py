from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from keiltool import cli


def test_flash_parser_preserves_legacy_generated_elf_and_explicit_elf_contract():
    parser = cli.build_parser()

    generated = parser.parse_args(["flash", "--project", "motor.uvprojx"])
    explicit = parser.parse_args(
        ["flash", "--project", "motor.uvprojx", "--elf", "build/motor.elf", "--probe", "cmsis-dap"]
    )

    assert generated.firmware is None
    assert generated.elf is None
    assert explicit.elf == Path("build/motor.elf")
    assert explicit.probe == "cmsis-dap"


def test_flash_parser_keeps_hex_and_bin_support_additive():
    args = cli.build_parser().parse_args(
        [
            "flash",
            "--project",
            "motor.uvprojx",
            "--firmware",
            "release/motor.bin",
            "--base-address",
            "0x08004000",
        ]
    )

    assert args.firmware == Path("release/motor.bin")
    assert args.elf is None
    assert args.base_address == 0x08004000


def test_cmd_flash_without_firmware_uses_generated_elf_and_probe_config(tmp_path, monkeypatch):
    target = SimpleNamespace(name="Debug Target", debug_probe="cmsis-dap")
    model = SimpleNamespace(targets=[target], inferred_project_root=str(tmp_path))
    generated_dir = tmp_path / ".keilbridge" / "generated"
    config_path = generated_dir / "openocd" / "Debug_Target_cmsis-dap.cfg"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("# generated probe config\n", encoding="utf-8")
    elf_path = tmp_path / ".keilbridge" / "build" / "gcc-debug" / "Debug_Target.elf"
    elf_path.parent.mkdir(parents=True)
    elf_path.write_bytes(b"\x7fELF")
    openocd = tmp_path / "openocd.exe"
    openocd.write_bytes(b"fake")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    captured = {}

    def fake_run_flash(config, request, log_dir, **kwargs):
        captured.update(config=config, request=request, log_dir=log_dir, kwargs=kwargs)
        return SimpleNamespace(
            success=True,
            returncode=0,
            command=["openocd", "-f", str(config_path)],
            stdout="Programming Finished\nVerified OK\n",
            stderr="",
            stdout_log=tmp_path / "flash.out.log",
            stderr_log=tmp_path / "flash.err.log",
            findings=[],
        )

    monkeypatch.setattr(cli, "parse_uvprojx", lambda _path: model)
    monkeypatch.setattr(cli, "find_openocd", lambda _path: str(openocd))
    monkeypatch.setattr(cli, "find_openocd_scripts", lambda _path: str(scripts))
    monkeypatch.setattr(cli, "run_flash", fake_run_flash)

    result = cli.cmd_flash(
        Namespace(
            project=tmp_path / "motor.uvprojx",
            target=None,
            probe=None,
            workspace_root=None,
            openocd=None,
            elf=None,
            firmware=None,
            base_address=0x08000000,
        )
    )

    assert result == 0
    assert captured["request"].firmware == elf_path
    assert captured["config"].interface_cfg is None
    assert Path(captured["config"].target_cfg) == config_path
    assert captured["kwargs"]["cwd"] == generated_dir
    assert captured["kwargs"]["target"] is target
    assert captured["kwargs"]["target_name"] == "Debug Target"
