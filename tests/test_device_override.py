from keiltool.core.device_override import apply_device_override
from keiltool.core.project_model import KeilTargetModel


def test_apply_device_override_updates_debug_and_memory_fields(tmp_path):
    override_dir = tmp_path / ".keilbridge"
    override_dir.mkdir()
    (override_dir / "device_override.json").write_text(
        """{
  "openocd_target": "target/custom.cfg",
  "probe": "cmsis-dap",
  "flash_algorithm": "custom.FLM",
  "memory": [
    {"name": "FLASH", "origin": "0x08002000", "length": "120K"},
    {"name": "RAM", "origin": "0x20000000", "length": "32K"}
  ]
}
""",
        encoding="utf-8",
    )
    target = KeilTargetModel(name="App")

    apply_device_override(target, tmp_path)

    assert target.device_info.openocd_target == "target/custom.cfg"
    assert target.debug_probe == "cmsis-dap"
    assert target.flash_algorithm == "custom.FLM"
    assert [(item.name, item.origin, item.length) for item in target.memory] == [
        ("FLASH", "0x08002000", "120K"),
        ("RAM", "0x20000000", "32K"),
    ]
