# KeilTool

KeilTool is a zero-intrusion external build adapter for existing Keil MDK projects.

It keeps the original Keil project untouched and generates an external GCC/CMake build, flash, and debug layer from `.uvprojx`, `.uvoptx`, `.sct`, and related project metadata.

## Direction

- Keil project remains the source of truth.
- No source files are moved or copied from the target project.
- No Keil project files are modified.
- Generated files stay under KeilTool-managed directories.
- CMake, flashing, and debugging are adapter layers, not replacements for Keil.
- STM32 and GD32 families are the first-class long-term targets.
- Bare-metal, standard peripheral libraries, CubeMX/HAL/LL, and RTOS projects should share one adapter model.

## First Document

See:

- [docs/00_KeilTool_零侵入Keil到CMake工具规划.md](docs/00_KeilTool_零侵入Keil到CMake工具规划.md)

## Initial MVP

The first milestone is a real STM32G4 Keil project flow:

```powershell
k2c inspect C:\Path\To\Project\MDK-ARM\App.uvprojx
k2c model C:\Path\To\Project\MDK-ARM\App.uvprojx --json
k2c configure --project C:\Path\To\Project\MDK-ARM\App.uvprojx
k2c build
```

Current usable command:

```powershell
python -m keiltool.cli inspect C:\Path\To\Project\MDK-ARM\App.uvprojx --target App -v
```
