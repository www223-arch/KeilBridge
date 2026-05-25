# KeilTool TODO

## Phase 0: Foundation

- [x] Create Python package structure.
- [x] Define `KeilProjectModel`.
- [ ] Define `keiltool.yaml`.
- [ ] Define generated directory layout.

## Phase 1: Keil Parser

- [x] Parse `.uvprojx` target list.
- [x] Select target by name.
- [x] Parse source files.
- [x] Parse include paths.
- [x] Parse preprocessor defines.
- [x] Parse libraries.
- [x] Parse startup file.
- [ ] Parse scatter file.
- [x] Parse device and CPU memory metadata.
- [x] Add first diagnostics for ARMCC defines, ARMCC libraries, startup, and scatter metadata.

## Phase 2: First Real Project

- [x] Inspect `HS_STEP_42C.uvprojx`.
- [x] Generate normalized JSON model.
- [x] Add STM32G431CBUx device database entry.
- [x] Discover generated Keil `.sct` when `ScatterFile` is empty.
- [x] Preview GNU ld script from basic Keil scatter file.
- [ ] Write generated GNU ld script to `.keiltool/generated/linker/`.
- [ ] Generate GCC startup for STM32G431.

## Phase 2.5: Project Classification

- [ ] Detect STM32CubeMX/HAL project shape.
- [ ] Detect STM32/GD standard peripheral library project shape.
- [ ] Detect register-only bare-metal project shape.
- [ ] Detect FreeRTOS.
- [ ] Detect RT-Thread.
- [ ] Detect other RTOS integration patterns.

## Phase 3: CMake Output

- [ ] Generate external `CMakeLists.txt`.
- [ ] Generate GCC toolchain file.
- [ ] Generate `CMakePresets.json`.
- [ ] Build elf/hex/bin/map.

## Phase 4: Flash and Debug

- [ ] Add ST-Link OpenOCD profile.
- [ ] Add CMSIS-DAP OpenOCD profile.
- [ ] Add J-Link profile.
- [ ] Generate VS Code Cortex-Debug config.
