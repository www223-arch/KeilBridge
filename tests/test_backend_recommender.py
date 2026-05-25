from keiltool.core.backend_recommender import recommend_backends
from keiltool.core.project_model import DeviceInfo, KeilFile, KeilTargetModel, MemoryRegion


def test_backend_recommender_keeps_gcc_first_when_armclang_tools_missing():
    target = KeilTargetModel(
        name="App",
        device="STM32F405RGTx",
        vendor="st",
        family="stm32f4",
        core="cortex-m4",
        fpu="fpv4-sp-d16",
        float_abi="hard",
        memory=[MemoryRegion("FLASH", "0x08000000", "1024K"), MemoryRegion("RAM", "0x20000000", "128K")],
        sources=[KeilFile("Core/Src/main.c", "source", "Application")],
        libraries=["Drivers/CMSIS/Lib/ARM/arm_cortexM4lf_math.lib"],
        startup_files=["MDK-ARM/startup_stm32f405xx.s"],
        scatter_file="STM32F405RGT6.sct",
        device_info=DeviceInfo(matched=True, openocd_target="target/stm32f4x.cfg"),
    )

    result = recommend_backends(target, armclang_root=r"Z:\not-exist", arm_gcc_root=None)

    assert result.recommended == "gcc"
    assert result.options[0].backend == "gcc"
    assert result.options[0].status in {"ready", "possible_after_fixes"}
    assert any(option.backend == "armclang" and option.status == "candidate_tool_missing" for option in result.options)
