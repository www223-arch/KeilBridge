# KeilTool TODO

## Phase 0: Foundation

- [x] Create Python package structure.
- [x] Define `KeilProjectModel`.
- [ ] Define `keiltool.yaml`.
- [x] Define generated directory layout.

## Phase 1: Keil Parser

- [x] Parse `.uvprojx` target list.
- [x] Select target by name.
- [x] Parse source files.
- [x] Parse include paths.
- [x] Parse preprocessor defines.
- [x] Parse libraries.
- [x] Parse startup file.
- [x] Parse scatter file.
- [x] Parse device and CPU memory metadata.
- [x] Add first diagnostics for ARMCC defines, ARMCC libraries, startup, and scatter metadata.

## Phase 2: First Real Project

- [x] Inspect `HS_STEP_42C.uvprojx`.
- [x] Generate normalized JSON model.
- [x] Add STM32G431CBUx device database entry.
- [x] Discover generated Keil `.sct` when `ScatterFile` is empty.
- [x] Preview GNU ld script from basic Keil scatter file.
- [x] Write generated GNU ld script to `.keilbridge/generated/linker/`.
- [x] Generate GCC startup for STM32G431.
- [x] Generate minimal CMSIS-DSP compatibility source for the sample project.
- [x] Keep user source files immutable and unmodified; real source syntax errors should fail the build.

## Phase 2.5: Project Classification

- [x] Detect STM32CubeMX/HAL project shape.
- [x] Detect STM32/GD standard peripheral library project shape.
- [ ] Detect register-only bare-metal project shape.
- [x] Detect FreeRTOS.
- [x] Detect RT-Thread.
- [ ] Detect other RTOS integration patterns.
- [x] Generate machine-readable project IR report.
- [x] Generate human-readable conversion report.

## Phase 2.6: GD32 Support

- [x] Add GD32 seed device database entries.
- [x] Detect GD32 standard peripheral library project shape.
- [x] Warn that GD32 OpenOCD targets require real board validation.
- [ ] Validate with a real GD32 Keil project and board.
- [ ] Add user override file for missing GD32 memory/debug metadata.
- [ ] Add CMSIS-Pack or vendor pack ingestion for broader GD32 coverage.

## Phase 2.7: CubeMX and RTOS Boundaries

- [x] Detect STM32CubeMX `.ioc` and generated project layout.
- [x] Document that CubeMX files are reused, not regenerated.
- [x] Detect common RTOS project shapes.
- [ ] Map FreeRTOS RVDS/ARMCC portable layer to GCC portable layer.
- [ ] Detect and diagnose conflicting FreeRTOS heap implementations.
- [ ] Add RT-Thread compiler-port diagnostics.

## Phase 3: CMake Output

- [x] Generate external `CMakeLists.txt`.
- [x] Generate GCC toolchain file.
- [x] Generate `CMakePresets.json`.
- [x] Build elf/hex/bin/map.

## Phase 4: Flash and Debug

- [x] Add ST-Link OpenOCD profile.
- [ ] Add CMSIS-DAP OpenOCD profile.
- [ ] Add J-Link profile.
- [x] Generate VS Code Cortex-Debug config.
- [ ] Add OpenOCD runtime discovery for STM32CubeIDE/xPack installs.
- [ ] Add `flash` command.
- [ ] Add `debug` command.
