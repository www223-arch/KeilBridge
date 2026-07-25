from __future__ import annotations

import json
import zipfile

import pytest

from keiltool.core.device_catalog import load_catalog_file
from keiltool.core.device_import import import_device_file, load_user_catalog


PDSC = """<?xml version="1.0" encoding="UTF-8"?>
<package>
  <vendor>Example</vendor><name>Example_DFP</name>
  <releases><release version="1.2.0"/></releases>
  <devices><family Dfamily="ExampleM4">
    <processor Dcore="Cortex-M4" Dfpu="1"/>
    <device Dname="EXAMPLE123">
      <memory name="Flash" start="0x08000000" size="0x40000" access="rx"/>
      <memory name="SRAM" start="0x20000000" size="0x10000" access="rwx"/>
    </device>
  </family></devices>
</package>
"""


def _custom(device: str = "CUSTOM123") -> dict[str, object]:
    return {
        "schema_version": 1,
        "vendor": "Custom",
        "device": device,
        "family": "CustomM4",
        "core": "Cortex-M4",
        "memory": [
            {"name": "Flash", "start": "0x08000000", "size": "0x40000", "access": "rx"},
            {"name": "SRAM", "start": "0x20000000", "size": "0x10000", "access": "rwx"},
        ],
        "openocd_target": "target/stm32f3x.cfg",
    }


def test_imports_direct_pdsc_and_pack_without_extracting(tmp_path):
    destination = tmp_path / "devices"
    pdsc = tmp_path / "Example.pdsc"
    pdsc.write_text(PDSC, encoding="utf-8")
    pack = tmp_path / "Example.pack"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("Example.pdsc", PDSC)

    direct = import_device_file(pdsc, destination)
    packed = import_device_file(pack, destination)

    assert direct.devices[0].device == "EXAMPLE123"
    assert direct.devices[0].source.kind == "imported_pdsc"
    assert packed.devices[0].source.kind == "imported_pack"
    assert direct.output_path.is_file()
    assert packed.output_path.is_file()
    assert not (destination / "Example.pdsc").exists()


def test_imports_valid_custom_json_with_explicit_target(tmp_path):
    source = tmp_path / "device.json"
    source.write_text(json.dumps(_custom()), encoding="utf-8")

    result = import_device_file(source, tmp_path / "devices")
    device = load_catalog_file(result.output_path)[0]

    assert device.device == "CUSTOM123"
    assert device.memory[1].start == 0x20000000
    assert device.openocd_target == "target/stm32f3x.cfg"
    assert device.openocd_status == "user_provided"


def test_custom_json_without_target_is_kept_as_information_only(tmp_path):
    payload = _custom()
    payload.pop("openocd_target")
    source = tmp_path / "device.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    result = import_device_file(source, tmp_path / "devices")

    assert result.devices[0].openocd_target == ""
    assert result.devices[0].openocd_status == "unresolved"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(memory=[]),
        lambda payload: payload.update(
            memory=[
                {"name": "A", "start": "0x20000000", "size": "0x100", "access": "rwx"},
                {"name": "B", "start": "0x20000080", "size": "0x100", "access": "rwx"},
            ]
        ),
        lambda payload: payload.update(openocd_target="../unsafe.cfg"),
    ],
)
def test_rejects_invalid_custom_json_without_changing_destination(tmp_path, mutate):
    destination = tmp_path / "devices"
    destination.mkdir()
    existing = destination / "existing.json"
    existing.write_text('{"keep": true}\n', encoding="utf-8")
    before = existing.read_bytes()
    payload = _custom()
    mutate(payload)
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        import_device_file(source, destination)

    assert existing.read_bytes() == before
    assert list(destination.iterdir()) == [existing]


def test_rejects_pack_traversal_multiple_descriptors_and_duplicate_keys(tmp_path):
    destination = tmp_path / "devices"
    traversal = tmp_path / "traversal.pack"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.pdsc", PDSC)
    multiple = tmp_path / "multiple.pack"
    with zipfile.ZipFile(multiple, "w") as archive:
        archive.writestr("one.pdsc", PDSC)
        archive.writestr("two.pdsc", PDSC)
    duplicate = tmp_path / "duplicate.pdsc"
    duplicate_xml = PDSC.replace(
        "</family>",
        """    <device Dname="EXAMPLE123">
      <memory name="SRAM" start="0x20000000" size="0x10000" access="rwx"/>
    </device>
  </family>""",
    )
    duplicate.write_text(duplicate_xml, encoding="utf-8")

    with pytest.raises(ValueError):
        import_device_file(traversal, destination)
    with pytest.raises(ValueError):
        import_device_file(multiple, destination)
    with pytest.raises(ValueError):
        import_device_file(duplicate, destination)
    assert not destination.exists()


def test_load_user_catalog_returns_valid_files_and_diagnostics(tmp_path):
    destination = tmp_path / "devices"
    source = tmp_path / "device.json"
    source.write_text(json.dumps(_custom()), encoding="utf-8")
    import_device_file(source, destination)
    (destination / "broken.json").write_text("{", encoding="utf-8")

    result = load_user_catalog(destination)

    assert [item.device for item in result.devices] == ["CUSTOM123"]
    assert len(result.diagnostics) == 1
    assert "broken.json" in result.diagnostics[0]
