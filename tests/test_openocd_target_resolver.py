from keiltool.core.openocd_target_resolver import resolve_openocd_target
from keiltool.core.project_model import KeilTargetModel
import pytest

from keiltool.generators.debug_generator import generate_debug_configuration, generate_openocd_config


def test_resolve_gd32f3_family_to_verified_stm32f3_target(tmp_path):
    scripts = tmp_path / "scripts"
    target_dir = scripts / "target"
    target_dir.mkdir(parents=True)
    (target_dir / "stm32f3x.cfg").write_text("# stm32f3\n", encoding="utf-8")
    target = KeilTargetModel(name="App", device="GD32F303CC", vendor="gd", family="gd32f3")

    result = resolve_openocd_target(target, scripts)

    assert result.target_cfg == "target/stm32f3x.cfg"
    assert result.status == "family_mapping_verified"


def test_resolve_gd32e2_family_to_verified_gd32e23x_target(tmp_path):
    scripts = tmp_path / "scripts"
    target_dir = scripts / "target"
    target_dir.mkdir(parents=True)
    (target_dir / "gd32e23x.cfg").write_text("# gd32e23x\n", encoding="utf-8")
    target = KeilTargetModel(name="App", device="GD32E235CB", vendor="gd", family="gd32e2")

    result = resolve_openocd_target(target, scripts)

    assert result.target_cfg == "target/gd32e23x.cfg"
    assert result.status == "family_mapping_verified"


def test_resolve_target_rejects_a_cfg_directory(tmp_path):
    scripts = tmp_path / "scripts"
    (scripts / "target" / "stm32f3x.cfg").mkdir(parents=True)
    target = KeilTargetModel(name="App", device="GD32F303CC", vendor="gd", family="gd32f3")

    result = resolve_openocd_target(target, scripts)

    assert result.target_cfg == ""
    assert result.status == "unresolved"


def test_generate_openocd_config_marks_unresolved_target_when_candidate_missing(tmp_path):
    scripts = tmp_path / "scripts"
    (scripts / "target").mkdir(parents=True)
    target = KeilTargetModel(name="App", device="GD32F303CC", vendor="gd", family="gd32f3")

    content = generate_openocd_config(target, "stlink", str(scripts))

    assert "OpenOCD target unresolved" in content
    assert "source [find target/gd32f3x.cfg]" not in content


def test_generate_debug_configuration_fails_instead_of_guessing_family_cfg():
    target = KeilTargetModel(name="App", device="UNKNOWN123", family="unknown123")

    with pytest.raises(ValueError, match="OpenOCD target could not be resolved"):
        generate_debug_configuration(
            target=target,
            probe="stlink",
            executable="App.elf",
            cwd=".",
            openocd_path="",
            openocd_scripts="",
            openocd_config="",
            pre_launch_task="",
        )
