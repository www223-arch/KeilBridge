from keiltool.core.keil_option_parser import parse_uvoptx_debug_options


def test_parse_uvoptx_debug_options_extracts_stlink_and_flash_algorithm(tmp_path):
    uvoptx = tmp_path / "demo.uvoptx"
    uvoptx.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<ProjectOpt>
  <Target>
    <TargetName>Target 1</TargetName>
    <TargetOption>
      <DebugOpt>
        <pMon>STLink\\ST-LINKIII-KEIL_SWO.dll</pMon>
      </DebugOpt>
      <TargetDriverDllRegistry>
        <SetRegEntry>
          <Name>-FP0($$Device:GD32F303CC$Flash\\GD32F30x_HD.FLM)</Name>
        </SetRegEntry>
      </TargetDriverDllRegistry>
    </TargetOption>
  </Target>
</ProjectOpt>
""",
        encoding="utf-8",
    )

    options = parse_uvoptx_debug_options(uvoptx, "Target 1")

    assert options.probe == "stlink"
    assert options.debug_dll == "STLink\\ST-LINKIII-KEIL_SWO.dll"
    assert options.flash_algorithm == "GD32F30x_HD.FLM"
