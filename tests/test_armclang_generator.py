from keiltool.core.project_model import KeilFile, KeilTargetModel, MemoryRegion
from keiltool.generators.armclang_generator import generate_armclang_cmakelists, generate_armclang_scatter_from_memory


def test_armclang_cmakelists_uses_axf_and_scatter_without_gcc_linker():
    target = KeilTargetModel(
        name="Demo",
        core="cortex-m4",
        fpu="fpv4-sp-d16",
        float_abi="hard",
        sources=[KeilFile("Core/Src/main.c", "source"), KeilFile("MDK-ARM/startup_demo.s", "startup")],
        includes=["Core/Inc"],
        defines=["USE_HAL_DRIVER", "__ARMCC_VERSION=6010050"],
        libraries=["Drivers/CMSIS/Lib/ARM/arm_cortexM4lf_math.lib"],
    )

    content = generate_armclang_cmakelists(target, "Demo.sct")

    assert "--scatter=Demo.sct" in content
    assert "arm_cortexM4lf_math.lib" in content
    assert "startup_demo.s" in content
    assert "-T${LINKER_SCRIPT}" not in content
    assert "arm-none-eabi-gcc" not in content


def test_armclang_scatter_can_be_generated_from_memory():
    target = KeilTargetModel(name="Demo")

    content = generate_armclang_scatter_from_memory(
        target,
        [
            MemoryRegion("FLASH", "0x08000000", "128K"),
            MemoryRegion("RAM", "0x20000000", "32K"),
        ],
    )

    assert "LR_IROM1 0x08000000 128K" in content
    assert "RW_IRAM1 0x20000000 32K" in content
