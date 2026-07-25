from __future__ import annotations


def test_parse_pdsc_inherits_processor_and_device_memory(tmp_path):
    from keiltool.core.cmsis_pack import parse_pdsc

    pdsc = tmp_path / "GigaDevice.GD32F30x_DFP.pdsc"
    pdsc.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<package>
  <vendor>GigaDevice</vendor>
  <url>https://example.invalid/pack/</url>
  <name>GD32F30x_DFP</name>
  <releases><release version="2.5.0" date="2025-08-20"/></releases>
  <devices>
    <family Dfamily="GD32F30x Series" Dvendor="GigaDevice:123">
      <processor Dcore="Cortex-M4" Dfpu="1" Dendian="Little-endian"/>
      <subFamily DsubFamily="GD32F303">
        <processor Dclock="120000000"/>
        <device Dname="GD32F303VE">
          <memory id="IROM1" start="0x08000000" size="0x080000" startup="1" default="1"/>
          <memory id="IRAM1" start="0x20000000" size="0x010000" default="1"/>
          <algorithm name="Flash/GD32F30x_HD.FLM" start="0x08000000" size="0x080000"/>
          <variant Dvariant="GD32F303VET6"/>
        </device>
      </subFamily>
    </family>
  </devices>
</package>
""",
        encoding="utf-8",
    )

    devices = parse_pdsc(pdsc)

    device = next(item for item in devices if item.device == "GD32F303VE")
    variant = next(item for item in devices if item.device == "GD32F303VET6")
    assert device.vendor == "GigaDevice"
    assert device.family == "GD32F30x Series"
    assert device.sub_family == "GD32F303"
    assert device.core == "Cortex-M4"
    assert device.fpu == "FPU"
    assert [(item.name, item.start, item.size, item.access) for item in device.memory] == [
        ("IROM1", 0x08000000, 0x080000, "rx"),
        ("IRAM1", 0x20000000, 0x010000, "rwx"),
    ]
    assert device.flash_algorithms == ("Flash/GD32F30x_HD.FLM",)
    assert device.source.pack_version == "2.5.0"
    assert variant.memory == device.memory
    assert variant.core == device.core


def test_parse_pdsc_child_memory_replaces_same_named_parent_region(tmp_path):
    from keiltool.core.cmsis_pack import parse_pdsc

    pdsc = tmp_path / "Vendor.Family.pdsc"
    pdsc.write_text(
        """<package>
  <vendor>Vendor</vendor><name>Family</name>
  <releases><release version="1.0.0"/></releases>
  <devices><family Dfamily="F">
    <processor Dcore="Cortex-M3"/>
    <memory name="SRAM" access="rwx" start="0x20000000" size="0x1000"/>
    <device Dname="PART">
      <memory name="SRAM" access="rwx" start="0x20000000" size="0x2000"/>
    </device>
  </family></devices>
</package>""",
        encoding="utf-8",
    )

    device = parse_pdsc(pdsc)[0]

    assert [(item.name, item.size) for item in device.memory] == [("SRAM", 0x2000)]

