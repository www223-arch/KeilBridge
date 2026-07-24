# KeilBridge

KeilBridge is a zero-intrusion adapter that bridges existing Keil MDK projects to GCC, ArmClang, OpenOCD, VS Code, and automation workflows.

It does not rewrite the original Keil project. Keil remains the source of truth.

## Direction

- Do not modify source files.
- Do not modify `.uvprojx`, `.uvoptx`, `.sct`, or `.ioc`.
- Do not move or copy the user project into the tool repository.
- Generate a per-project `.keilbridge/` workspace under the target Keil project root by default.
- Keep multiple Keil projects isolated from each other.
- Prefer STM32 and GD32 as first-class long-term targets.

## Current Commands

```powershell
python -m keiltool.cli inspect "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App -v

python -m keiltool.cli doctor backend --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App

python -m keiltool.cli configure --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --backend gcc

python -m keiltool.cli build --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --backend gcc

python -m keiltool.cli configure --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --backend debug-only --elf "C:\Path\To\Project\MDK-ARM\App\App.axf"

python -m keiltool.cli doctor flash --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --run

k2c gui
```

`k2c gui` launches the ST-Link/OpenOCD workbench for programming an existing HEX/BIN package or attaching to SEGGER RTT. It restores its last non-sensitive settings, performs no hardware operation at startup, and keeps Flash and RTT as separate mutually exclusive ST-Link actions. See the user guide for target verification, RTT no-reset behavior, and log locations.

## Required Environment

- Python 3.10+
- OpenOCD, preferably xPack OpenOCD or STM32CubeCLT OpenOCD for STM32/GD32 targets
- Arm GNU Toolchain `arm-none-eabi-gdb` for GDB-based debug
- VS Code extensions: Cortex-Debug and C/C++
- For GCC backend: CMake, Ninja, Arm GNU Toolchain `arm-none-eabi-gcc`
- For ArmClang backend: Keil MDK Arm Compiler 6 tools such as `armclang`, `armlink`, `fromelf`
- For debug-only backend: an existing Keil `.axf` or `.elf` with debug symbols

## Documents

- [KeilBridge user guide](docs/01_KeilBridge_用户使用手册.md)
- [KeilBridge FAQ](docs/03_KeilBridge_FAQ.md)
- [KeilBridge planning document](docs/00_KeilTool_零侵入Keil到CMake工具规划.md)
