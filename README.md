# KeilBridge

KeilBridge is a zero-intrusion adapter that bridges existing Keil MDK projects to GCC, CMake, OpenOCD, VS Code, and automation workflows.

It does not rewrite the original Keil project. Keil remains the source of truth.

## Direction

- Do not modify source files.
- Do not modify `.uvprojx`, `.uvoptx`, `.sct`, or `.ioc`.
- Do not move or copy the user project into the tool repository.
- Generate a per-project `.keilbridge/` workspace under the target Keil project root by default.
- Keep multiple Keil projects isolated from each other.
- Prefer STM32 and GD32 as first-class long-term targets.

## Generated Workspace

By default:

```text
<keil-project-root>/.keilbridge/generated
<keil-project-root>/.keilbridge/build
```

This means project A and project B each get their own `.keilbridge/` directory, so switching between projects does not overwrite generated files or build caches.

## Current Commands

```powershell
python -m keiltool.cli inspect "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App -v

python -m keiltool.cli configure --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink

python -m keiltool.cli build --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App

python -m keiltool.cli openocd --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink
```

## Documents

- [KeilBridge planning document](docs/00_KeilTool_零侵入Keil到CMake工具规划.md)
- [KeilBridge user guide](docs/01_KeilBridge_用户使用手册.md)
