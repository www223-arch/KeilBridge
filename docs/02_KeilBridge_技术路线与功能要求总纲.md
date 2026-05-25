# KeilBridge 技术路线与功能要求总纲

## 1. 产品定位

KeilBridge 不是“万能 Keil 转 GCC 工具”，也不是为了炫技把所有工程强行 CMake 化。

更准确的定位是：

> KeilBridge 是一个面向 Keil 遗留工程的零侵入桥接、诊断与调试自动化工具。

它的实际意义是把 Keil 工程中的构建、烧录、调试、寄存器、内存、调用栈、Fault 现场和迁移风险，变成可脚本化、可复现、可诊断、可被 AI 读取的结构化流程。

核心价值：

- 让用户不用在 Keil、VS Code、OpenOCD、GDB、AI 之间手工搬运信息。
- 让工程不只是“能编译/能烧录”，还要能解释为什么不能正常运行。
- 对能迁移的工程生成现代工作区；对不能迁移的工程给出清晰兜底路线。
- 所有失败都进入 Doctor，而不是让用户面对散乱的 GCC/OpenOCD/GDB 原始报错。

## 2. 总原则

- 原 Keil 工程是事实源。
- 不修改用户源码。
- 不修改 `.uvprojx/.uvoptx/.ioc/.sct`。
- 不移动工程目录结构。
- 所有生成物放在目标工程自己的 `.keilbridge/`。
- 生成层可以有 overlay 副本，但原工程不动。
- 用户源码本身有错误就正常报错，不默认替用户修源码。
- 自动识别永远有边界，必须允许 override。
- 工具负责推荐路线，最终选择权属于用户。

## 3. 后端策略

KeilBridge 必须把 Build Backend 和 Debug Backend 解耦。

### 3.1 Build Backend

#### GCC backend

定位：

- 面向开放化、CI、跨平台、长期标准化。

适合：

- 新工程。
- 无闭源 ARMCC `.lib`。
- scatter 简单。
- startup 可生成或可替换。
- RTOS port 可切换到 GCC。
- 团队希望摆脱 Keil/Arm 授权环境。

风险：

- `.sct` 要转 `.ld`。
- ARMASM startup 要转换。
- ARMCC `.lib` 可能不能链接。
- ARMCC 语法、内联汇编、RTOS port、特殊 section 都要诊断。

#### ArmClang backend

定位：

- 面向 Keil 遗留工程的兼容迁移后端。

适合：

- 原工程强依赖 Keil/Arm Compiler 生态。
- 使用 `.sct`、ARMASM startup、Arm 编译器扩展。
- 有 ARMCC/Keil 风格库。
- 用户想先脱离 Keil IDE GUI，但不急着 GCC 化。

风险：

- 安装、授权、路径、版本复杂。
- ARMCC5 `.lib` 不保证无痛兼容。
- 仍然需要 GDB Server/GDB 才能做自动调试。

#### Keil CLI fallback

定位：

- 保底构建后端。

适合：

- 工程短期不能脱离 Keil 构建。
- 闭源库太多。
- 历史包袱重。
- 需要保持原构建结果作为对照基准。

#### debug-only

定位：

- 兜底、诊断、过渡和故障现场采集模式。

适合：

- 已有 Keil AXF/ELF。
- 当前只想采集 HardFault、寄存器、调用栈、变量。
- 工程暂时无法迁移。

不适合：

- 日常自然打断点主工作流。

原因：

- 源码路径可能和当前工作区不一致。
- 没有统一 `compile_commands.json`。
- 构建、烧录、调试不是同一链路。
- AXF/ELF 可能不是当前源码最新产物。

### 3.2 Debug Backend

首批支持：

- OpenOCD + GDB/GDB-MI。
- J-Link GDB Server + GDB/GDB-MI。

后续可选：

- pyOCD + GDB/GDB-MI。

核心结论：

- 自动调试不依赖 GCC。
- 只要有带符号的 ELF/AXF，并能接 GDB Server，就可以做断点、寄存器、内存、调用栈、Fault dump。

## 4. 后端推荐器

KeilBridge 必须提供 Backend Recommender，而不是默认强推 GCC。

命令建议：

```powershell
python -m keiltool.cli doctor backend --project "<project.uvprojx>" --target "<target>"
```

或在 `inspect -v` 末尾输出：

```text
Backend recommendation:
  gcc: possible / blocked / recommended
  armclang: possible / recommended / unknown
  debug-only: fallback / diagnostic
  keil-cli: fallback
```

推荐依据：

- 是否有 ARMCC `.lib`。
- 是否有 `.sct`。
- startup 是否 ARMASM。
- 是否存在 ARMCC 专用宏和语法。
- 是否有复杂自定义 section。
- 是否有 RTOS，以及 port 是否可映射。
- 是否有 CubeMX/HAL 标准结构。
- 是否有闭源中间件。
- 用户目标是日常开发，还是只采集调试现场。

## 5. Doctor 系统

Doctor 是 KeilBridge 通用性的核心。

不应该让用户面对原始错误，而要输出：

```text
发生了什么
为什么发生
属于哪一层问题
能否自动处理
推荐哪个 backend
下一步命令是什么
报告文件在哪里
```

### 5.1 Scan Doctor

目标：

- 解析 Keil 工程并生成 `project_ir.json`。
- 识别芯片、内核、FPU、内存、source/include/define/library。
- 识别 CubeMX、HAL、标准库、RTOS、中间件。
- 识别 startup、scatter、`.lib`、自定义 section。

### 5.2 CMake Doctor

目标：

- 不编译，只检查生成文件是否完整。

检查：

- `CMakeLists.txt`。
- toolchain file。
- linker script。
- startup。
- OpenOCD cfg。
- VS Code workspace。
- `compile_commands.json` 预期路径。

### 5.3 Build Doctor

目标：

- 将 GCC/ArmClang 编译错误分类。

典型分类：

- ARMASM 被 GCC 编译。
- ARMCC `.lib` 不能链接。
- include path 缺失。
- define 缺失。
- C++ 严格性差异。
- CMSIS-DSP 符号缺失。
- FreeRTOS port 不匹配。

### 5.4 ELF Doctor

目标：

- 编译链接成功后，检查“能不能正常启动运行”的关键条件。

必须检查：

- 向量表地址和 MSP/Reset_Handler。
- `_estack/_sdata/_edata/_sidata/_sbss/_ebss`。
- `.data` 是否覆盖所有需要复制的 SRAM 段。
- `.bss` 是否覆盖所有需要清零的段。
- `.ccmram` / `.CCM` 初始化。
- `.preinit_array/.init_array/.fini_array/.ctors/.dtors`。
- `__libc_init_array`。
- 是否存在 RAM orphan section。
- FreeRTOS `SVC/PendSV/SysTick` 映射。
- FLASH/RAM/CCMRAM 使用率。

真实踩坑已经证明：

- 漏 `.CCM` 会导致外设实例表未初始化。
- 漏 `.init_array` 会导致 C++ 全局对象虚表未初始化。
- 漏 `.SRAM` 会导致 `__SRAM` 对象成为 orphan，startup 不复制。

### 5.5 Flash Doctor

目标：

- 检查烧录链路，而不是证明业务能跑。

检查：

- OpenOCD/J-Link 路径。
- 是否使用 ESP-IDF OpenOCD 调 STM32/GD32。
- probe 类型。
- OpenOCD cfg。
- DPIDR、芯片识别、flash size。
- program/verify 是否成功。
- CMSIS-DAP command mismatch。
- CMD_INFO failed。
- reset 后 PC/MSP 是否合理。

### 5.6 Debug Doctor

目标：

- 不盲目 continue 到 main，先做复位健康检查和 Fault 现场采集。

检查：

- reset halt。
- PC/MSP/PSP/LR/xPSR。
- CFSR/HFSR/MMFAR/BFAR。
- 异常栈帧原始 PC/LR。
- `addr2line` 反查。
- 调用栈。
- 是否命中 HardFault/MemManage/BusFault/UsageFault。

输出：

- `debug_result.json`。
- `fault_dump.md`。

### 5.7 Compat Doctor

目标：

- 识别 ARMCC/Keil 语法和编译器差异。

分级：

- A 类：自动兼容，例如宏映射。
- B 类：生成 overlay 或 patch，用户确认。
- C 类：必须人工处理，例如复杂内联汇编。

### 5.8 Lib Doctor

目标：

- 判断库文件对不同 backend 的兼容性。

输出矩阵：

```text
Library              GCC       ArmClang    Keil
arm_xxx.lib          blocked   maybe       supported
libxxx.a             supported unknown     unknown
```

建议：

- 有源码则源码重编。
- 有 GCC `.a` 则替换。
- 只有 ARMCC `.lib`，GCC backend blocked。
- 推荐 ArmClang 或 Keil CLI fallback。

## 6. 功能要求

### 6.1 CLI

当前命令继续保留：

```powershell
inspect
configure
build
flash
doctor flash
```

新增命令优先级：

```powershell
doctor elf
doctor backend
doctor debug
doctor build
doctor lib
doctor all
```

中期命令：

```powershell
configure --backend gcc
configure --backend armclang
build --backend gcc
build --backend armclang
debug --backend openocd-gdb
debug-only --elf "<firmware.axf>"
```

## 12. 当前实现进度：GCC / ArmClang 后端选择入口

本阶段先把“第一次建 `.keilbridge` 工作区前必须扫描整个项目并推荐后端”做成正式能力。

已实现命令：

```powershell
python -m keiltool.cli doctor backend --project "<project.uvprojx>" --target "<target>"
python -m keiltool.cli configure --project "<project.uvprojx>" --target "<target>" --backend auto
python -m keiltool.cli configure --project "<project.uvprojx>" --target "<target>" --backend gcc
python -m keiltool.cli doctor elf --project "<project.uvprojx>" --target "<target>"
```

行为边界：

- `doctor backend` 只做项目事实扫描和后端推荐，不生成 CMake，不接触硬件。
- `configure --backend auto` 只写入后端推荐报告，让用户选择 `gcc` 或 `armclang`，不默认替用户迁移。
- `configure --backend gcc` 继续走当前已经验证过的 GCC/CMake/OpenOCD 路线。
- `configure --backend armclang` 现在只接受选择并输出明确边界：ArmClang 完整 CMake/ArmLink 生成仍在后续实现，不伪装成已完成。
- `doctor elf` 在 build 后检查启动和链接语义，重点覆盖 `.init_array`、`.CCM/.ccmram`、RAM orphan section、FreeRTOS handler 等曾经导致“能烧录但运行 HardFault”的问题。

生成报告：

```text
<keil-project-root>\.keilbridge\generated\reports\backend_recommendation.md
<keil-project-root>\.keilbridge\generated\reports\backend_recommendation.json
<keil-project-root>\.keilbridge\generated\reports\elf_doctor_report.md
<keil-project-root>\.keilbridge\generated\reports\elf_doctor_result.json
```

后续 ArmClang 开发必须按以下顺序推进：

1. 完成 ArmClang 工具链探测和版本报告：`armclang/armlink/armasm/fromelf`。
2. 生成 ArmClang 专属工作区，构建产物目录使用 `.keilbridge/build/armclang-debug`，避免和 GCC 产物互相覆盖。
3. 优先复用或生成 `.sct`，使用 `armlink` 保持接近 Keil 的链接语义。
4. 保留 Debug Backend 解耦：ArmClang 构建出的 ELF/AXF 仍然可以走 OpenOCD/J-Link GDB Server 调试。
5. 每个 ArmClang 工程先跑 `doctor backend`、`build`、`doctor elf`，再进入 flash/debug。

### 6.2 工作区生成

必须生成：

- 多根 `.code-workspace`。
- 原始源码根。
- generated 根。
- 绝对路径 `cmake.exe` / `ninja.exe`。
- `compile_commands.json` 指向。
- Cortex-Debug 配置。
- OpenOCD cfg。
- reports。

禁止：

- 让用户只打开 `.keilbridge/generated`。
- VS Code task 依赖 PATH 里的 `cmake`。
- generated 和 workspace 两套配置不一致。

### 6.3 GCC backend

必须覆盖：

- startup 生成。
- GNU ld 生成。
- `.data/.bss/.ccmram/.SRAM/.init_array`。
- C++ 全局对象。
- FreeRTOS GCC port 映射。
- ARMCC-only define 过滤。
- CMSIS-DSP 最小兜底与风险报告。
- `objcopy` hex/bin/map/size。

### 6.4 ArmClang backend

Spike 目标：

- 找到 `armclang/armlink/fromelf`。
- CMake 调 ArmClang。
- 优先复用 `.sct`。
- 生成 AXF/ELF。
- fromelf 生成 hex/bin。
- OpenOCD/J-Link 可加载符号调试。
- VS Code 能自然断点。

### 6.5 Debug-only

必须支持：

- 输入 AXF/ELF。
- 指定源码根。
- 路径映射。
- OpenOCD/J-Link GDB Server。
- break main / break HardFault。
- 采集寄存器、栈、内存、调用栈。
- 输出结构化报告。

### 6.6 Override

需要 `keilbridge.yaml` 或 `board.override.yaml`。

覆盖项：

- backend 选择。
- 工具链路径。
- OpenOCD/J-Link 路径。
- OpenOCD target cfg。
- probe。
- flash/ram/ccmram。
- app offset / bootloader offset。
- 替代库路径。
- CMSIS-DSP 根目录。
- RTOS port override。
- source path mapping。

## 7. 分阶段开发路线

### 阶段 0：稳定当前 GCC 闭环

目标：

- 对已验证工程做到 build/flash/debug/run 基础稳定。

必须完成：

- `doctor elf`。
- RAM orphan section 检查。
- `.SRAM` 归并。
- C++ 构造表检查。
- FreeRTOS handler 检查。
- HardFault 自动采集脚本。

验收：

- 24Sentry 运行 10 秒不进 HardFault。
- 25Sentry 同样跑过。
- GD32F303 同样跑过。
- `pytest` 覆盖 linker/startup 关键段。

### 阶段 1：Backend Recommender

目标：

- 工具基于工程事实推荐 GCC / ArmClang / debug-only / Keil CLI。

验收：

- 42Step 给出 GCC possible，但 ARMCC DSP `.lib` 风险。
- 24/25Sentry 给出 GCC possible after generated-layer fixes，ArmClang also reasonable，debug-only fallback。
- 只含 ARMCC `.lib` 且无源码的工程，GCC blocked。

### 阶段 2：Doctor 全链路

目标：

- 让每次失败都有报告。

实现：

- `doctor scan`。
- `doctor build`。
- `doctor elf`。
- `doctor flash`。
- `doctor debug`。
- `doctor lib`。
- `doctor all`。

验收：

- 报告写入 `.keilbridge/generated/reports/`。
- JSON 和 Markdown 同时输出。
- 终端输出下一步建议命令。

### 阶段 3：ArmClang backend Spike

目标：

- 验证 ArmClang 是否能作为 Keil 遗留工程主推荐路线。

范围：

- 一个 STM32F4 Sentry 工程。
- 一个 STM32G4 42Step 工程。
- 一个 GD 工程。

验收：

- 能 configure/build。
- 能生成 AXF/ELF/hex/bin。
- 能 OpenOCD/J-Link 调试。
- VS Code 能断到原始源码。

### 阶段 4：Debug-only

目标：

- 不迁移工程，也能采集调试现场。

验收：

- 输入 Keil 生成 AXF。
- 能 reset/halt。
- 能 break main。
- 能 break HardFault。
- 能生成 fault dump。
- 支持源码路径映射。

### 阶段 5：库与 CMSIS-DSP

目标：

- 不再靠 `arm_math_compat.c` 长期兜底。

实现：

- Lib Doctor。
- CMSIS-DSP source adapter。
- GCC `.a` 搜索。
- ArmClang/Keil fallback 推荐。

### 阶段 6：芯片与探针扩展

目标：

- STM32/GD32 覆盖扩大，但不虚假承诺。

实现：

- 设备数据库 seed。
- CMSIS-Pack 接入。
- OpenOCD/J-Link target 映射。
- probe profiles。

验收：

- 每个型号必须有 inspect/build/flash/debug 记录。
- 未实板验证的型号标记为 unverified。

## 8. 当前已知高风险清单

已经修复：

- `.CCM` 未初始化。
- C++ `.init_array` 缺失。
- `.SRAM` orphan section。
- VS Code preLaunchTask 依赖 PATH。
- `flash` 失败不保存日志。
- CMSIS-DAP command mismatch 没有 Doctor 分类。

仍需重点跟进：

- `doctor elf` 正式 CLI。
- Debug Doctor 自动 Fault dump。
- ArmClang backend。
- Lib Doctor。
- CMSIS-DSP 正式 adapter。
- 独立 OpenOCD 推荐与路径发现。
- J-Link GDB Server。
- override 文件。

## 9. 后续开发铁律

- 每解决一个真实工程问题，沉淀为 Doctor 规则。
- 每修一个生成层 bug，补测试。
- 每新增一个用户命令，更新用户手册。
- 每个 backend 都必须有清晰边界。
- 每个“支持”都必须说明验证范围。
- 不用“完美适配所有工程”这种不可验证表述。
- 用户看到的应该是可执行命令、报告路径、原因和下一步，而不是技术名词堆砌。
