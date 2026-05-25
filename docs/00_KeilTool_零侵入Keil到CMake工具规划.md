# KeilBridge 零侵入 Keil 到 CMake 工具规划

## 0. 英文命名

工具英文名：**KeilBridge**。

Bridge 表达“桥接”而不是“改造”。KeilBridge 的职责是在 Keil MDK 工程和 CMake/GCC/OpenOCD/VS Code/自动化流程之间建立外部适配层，强调 0 侵入、并行构建、调试桥接和工程自动化。CLI 短命令可以继续使用 `k2c`，作为 Keil to CMake 的开发者入口。

## 1. 项目定位

KeilBridge 是一个面向嵌入式工程的外部构建适配器。

它不把 Keil 工程“改造成” CMake 工程，而是在 Keil 工程外部生成一层现代构建、烧录、调试入口。

核心原则：

- 原 Keil 工程是唯一事实源。
- 不移动源码，不改目录结构，不修改 `.uvprojx/.uvoptx/.sct/.ioc`。
- 所有 CMake、VS Code、烧录、缓存、日志产物都放在 KeilBridge 自己的工作区。
- Keil 能继续照常使用，CMake 只是并行构建入口。

一句话目标：

> 给现有 Keil 工程外挂一套可复现、可自动化、可扩展的 GCC/CMake 构建和调试系统。

## 2. 非目标

为了保持技术边界清晰，KeilBridge 第一阶段不做这些事：

- 不重排用户工程目录。
- 不把目标工程源码复制到工具仓库。
- 不要求用户手工维护 CMake 源文件列表。
- 不承诺任意 ARMCC 私有库都能被 GCC 直接链接。
- 不承诺所有厂商、所有芯片一次性通用。
- 不直接替代 Keil Pack 管理器。

工具可以给出自动修复、替换建议和诊断报告，但默认不修改原工程。

## 3. 用户体验

目标体验应该足够短：

```powershell
k2c configure --project C:\Path\To\Project\MDK-ARM\App.uvprojx --target App
k2c build
k2c flash --probe stlink
k2c debug --probe cmsis-dap
```

也支持写入一个本地配置文件：

```powershell
k2c init --project C:\Path\To\Project\MDK-ARM\App.uvprojx
k2c build
```

生成物示例：

```text
<keil-project-root>/
  .keilbridge/
    generated/
      CMakeLists.txt
      CMakePresets.json
      cmake/
      linker/
      startup/
      vscode/
    build/
    cache/
    logs/
```

`.keilbridge/` 默认放在目标 Keil 工程根目录下。这样每个工程天然隔离，多个 Keil 工程来回编译不会互相覆盖。KeilBridge 不修改源码、不修改 `.uvprojx`、不修改 Keil 配置文件，只新增可删除、可再生成的工具工作区。

## 4. 总体架构

```text
KeilTool/
  keiltool/
    cli.py
    core/
      keil_parser.py
      project_model.py
      path_resolver.py
      diagnostics.py
    generators/
      cmake_generator.py
      presets_generator.py
      vscode_generator.py
      linker_generator.py
      startup_generator.py
    adapters/
      generic_arm/
      stm32/
      gd32/
    probes/
      openocd.py
      jlink.py
      pyocd.py
    data/
      devices/
      probes/
      templates/
  docs/
  tests/
```

架构分层：

- Parser：读取 Keil 工程文件，提取原始信息。
- Model：把 Keil 信息归一化成工具内部模型。
- Adapter：处理不同芯片厂商、系列、启动文件、链接脚本差异。
- Generator：生成 CMake、Presets、VS Code、linker script、startup。
- Probe Backend：适配 ST-Link、CMSIS-DAP、J-Link、pyOCD、OpenOCD。
- Diagnostics：提前发现 GCC 无法直接兼容的点，并给出明确处理策略。

## 5. 中间模型

所有生成器都只依赖中间模型，不直接依赖 `.uvprojx`。

示例：

```json
{
  "target": "HS_STEP_42C",
  "project_file": "C:/Users/86199/Desktop/42Step/MCU_userapp_motor/MDK-ARM/HS_STEP_42C.uvprojx",
  "project_root": "C:/Users/86199/Desktop/42Step/MCU_userapp_motor",
  "keil_project_dir": "C:/Users/86199/Desktop/42Step/MCU_userapp_motor/MDK-ARM",
  "device": "STM32G431CBUx",
  "core": "cortex-m4",
  "fpu": "fpv4-sp-d16",
  "float_abi": "hard",
  "sources": [],
  "includes": [],
  "defines": [],
  "libraries": [],
  "startup": "",
  "scatter": "",
  "memory": {
    "flash_origin": "0x08000000",
    "flash_size": "128K",
    "ram_origin": "0x20000000",
    "ram_size": "32K"
  }
}
```

## 6. Keil 解析范围

第一阶段解析 `.uvprojx`：

- TargetName
- Device
- Cpu
- Define
- IncludePath
- FilePath
- Group
- ScatterFile
- OptimizationLevel
- C99Mode
- library file
- startup file

第二阶段补充 `.uvoptx`：

- 当前活动 target
- 调试器类型
- 下载算法
- 用户配置的调试参数
- 输出目录信息

路径解析规则：

- `.uvprojx` 中的相对路径按 `.uvprojx` 所在目录解析。
- 生成的 CMake 使用绝对路径，避免工作目录变化导致失败。
- 所有路径在内部统一为 POSIX 风格，写文件时按目标格式输出。

## 7. GCC 兼容适配

KeilBridge 必须把“不兼容点”工具化，而不是甩给用户手动改。

### 7.1 Startup

Keil ARMASM `.s` 通常不能直接交给 GCC。

处理策略：

1. 优先在工程或芯片包中寻找 GCC 版 startup。
2. 找不到时，根据芯片型号和向量表模板生成 GCC startup。
3. 生成文件放入 `.keilbridge/generated/startup/`。

### 7.2 Linker Script

Keil scatter `.sct` 不能直接给 GNU ld。

处理策略：

1. 解析常见 `LR_IROM1 / ER_IROM1 / RW_IRAM1` 结构。
2. 转换为 GNU ld `.ld`。
3. 如果 scatter 复杂到无法自动转换，生成诊断报告并要求显式 override。

### 7.3 宏定义

过滤 Keil/ARMCC 专有宏：

```text
__CC_ARM
__ARMCC_VERSION
ARMCOMPILER
```

保留业务宏和 HAL/CMSIS 宏：

```text
USE_HAL_DRIVER
STM32G431xx
ARM_MATH_CM4
ARM_MATH_MATRIX_CHECK
ARM_MATH_ROUNDING
```

### 7.4 静态库

ARMCC `.lib` 不能假定可被 GCC 链接。

处理策略：

- CMSIS-DSP：优先替换为 GCC 兼容库或源码构建。
- 普通第三方库：尝试识别格式；不兼容时输出阻断级诊断。
- 用户可在 `keilbridge.yaml` 中配置替代库路径。

当前边界：

- KeilBridge 会检测 `arm_cortexM4lf_math.lib` 这类 ARMCC CMSIS-DSP 库，并在诊断中报告 `armcc_library`。
- 当前生成层不会把 ARMCC `.lib` 直接交给 GCC 链接。
- 为了打通早期样例工程，当前只生成最小 `arm_math_compat.c`，覆盖少量已验证符号，例如 `arm_sin_f32`、`arm_cos_f32`。
- 这只是兼容兜底，不等价于完整 CMSIS-DSP 支持。如果用户工程调用 `arm_mat_mult_f32`、`arm_pid_f32`、`arm_rfft_fast_f32`、`arm_biquad_cascade_df1_f32` 等未覆盖 API，仍可能在链接阶段出现 `undefined reference`。
- 完整方案必须实现 CMSIS-DSP adapter：优先使用工程内 CMSIS-DSP 源码，或链接 GCC/arm-none-eabi 可用的 `.a`，或要求用户通过 override 配置 DSP pack/root。

## 8. 芯片与烧录器抽象

芯片适配不写死在 CMake 里，而放到设备数据库和厂商 adapter。

设备条目示例：

```yaml
STM32G431CBUx:
  vendor: st
  family: stm32g4
  core: cortex-m4
  fpu: fpv4-sp-d16
  float_abi: hard
  flash:
    origin: 0x08000000
    size: 128K
  ram:
    origin: 0x20000000
    size: 32K
  openocd_target: target/stm32g4x.cfg
```

烧录器 profile 示例：

```yaml
stlink:
  backend: openocd
  interface: interface/stlink.cfg

cmsis-dap:
  backend: openocd
  interface: interface/cmsis-dap.cfg

jlink:
  backend: jlink

pyocd:
  backend: pyocd
```

构建、烧录、调试分离：

- CMake 负责生成 elf/hex/bin。
- Probe backend 负责 flash/debug。
- VS Code 配置由 probe profile 生成。

## 9. 配置文件规范

`keilbridge.yaml` 是用户可编辑配置，保存 override，不保存自动解析出来的大量清单。

示例：

```yaml
project: C:/Users/86199/Desktop/42Step/MCU_userapp_motor/MDK-ARM/HS_STEP_42C.uvprojx
target: HS_STEP_42C

toolchain:
  compiler: gcc-arm-none-eabi

probe:
  default: stlink

overrides:
  libraries:
    replace:
      C:/Users/86199/Desktop/42Step/MCU_userapp_motor/DSP_LIB/arm_cortexM4lf_math.lib: C:/Toolchains/CMSIS-DSP/libarm_cortexM4lf_math.a
```

## 10. 诊断等级

诊断输出分四级：

- info：普通信息。
- warning：可能影响结果，但不阻断。
- error：构建无法继续。
- unsupported：当前工具版本明确不支持，需要 adapter 或 override。

典型诊断：

```text
[warning] 检测到 Keil 专有宏 __CC_ARM，已从 GCC 构建宏中移除。
[error] 检测到 ARMCC 静态库 arm_cortexM4lf_math.lib，GCC 无法可靠链接。请配置替代库或启用 CMSIS-DSP 源码构建。
[info] 已从 scatter file 推导 FLASH=128K RAM=32K。
```

## 11. MVP 范围

第一期只追求把一个真实 STM32G4 HAL/Keil 工程 0 侵入跑通。

支持范围：

- Windows + PowerShell。
- Python CLI。
- Keil `.uvprojx` 单 target 解析。
- STM32G431CBUx。
- Cortex-M4F GCC 参数。
- `.sct` 到 `.ld` 基础转换。
- GCC startup 模板生成。
- CMakePresets 生成。
- Ninja 构建。
- ST-Link / CMSIS-DAP / J-Link profile 初版。
- VS Code Cortex-Debug 配置生成。

验收标准：

```text
k2c configure 成功生成外部构建层
k2c build 成功生成 elf/hex/bin/map
k2c flash --probe stlink 可调用烧录流程
原 Keil 工程目录无任何文件改动
```

代码规范：

- 工具源码必须保留详细中文注释。
- 注释重点解释工程化边界、兼容策略、Keil/GCC 差异和后续扩展点。
- 注释不写空话，不重复代码字面含义。
- 对 parser、adapter、generator、diagnostics 等核心模块，应在类、函数和关键分支处说明设计意图。
- 面向用户的诊断信息可以先使用英文，后续统一接入中英文消息表。

## 12. 分阶段路线

### 阶段 0：项目骨架

- 建立 Python 包结构。
- 定义中间模型。
- 定义配置文件格式。
- 定义生成物目录规范。

### 阶段 1：解析器

- 解析 `.uvprojx`。
- 支持 target 选择。
- 解析源文件、头文件、宏、库、startup、scatter、device。
- 输出 JSON 中间模型。

### 阶段 2：STM32G4 适配

- 建立 STM32G431CBUx 设备条目。
- 生成 GCC startup。
- 转换 `.sct` 为 `.ld`。
- 过滤 ARMCC 专用宏。

### 阶段 3：CMake 生成

- 生成 CMakeLists。
- 生成 toolchain 文件。
- 生成 CMakePresets。
- 生成 elf/hex/bin/map。

### 阶段 4：烧录和调试

- OpenOCD ST-Link。
- OpenOCD CMSIS-DAP。
- J-Link。
- VS Code launch/tasks/settings。

### 阶段 5：通用化

- STM32F1/F4/G4/H7/L4。
- GD32。
- 多 target。
- per-file options。
- CMSIS-DSP 自动替换策略。

## 13. 近期执行顺序

下一步从最小闭环开始：

1. 创建 KeilBridge Python 项目骨架。
2. 实现 `k2c inspect <uvprojx>`，只解析并打印工程摘要。
3. 实现 `k2c model <uvprojx> --json`，输出中间模型。
4. 用 `HS_STEP_42C.uvprojx` 做第一条真实样例。
5. 再开始生成 CMake。

这样每一步都可验证，不会一开始就把所有问题混在一起。

## 14. 长期适配目标：STM/GD 全系列优先

KeilBridge 的长期目标不是只服务某一个工程，而是形成一个可扩展的 Keil 外部构建适配平台。

优先覆盖范围：

- ST STM32 全系列：F0/F1/F2/F3/F4/F7/G0/G4/H5/H7/L0/L1/L4/L5/U0/U5/WB/WL 等。
- GigaDevice GD32 全系列：GD32F1/F3/F4/E2/E5/GD32A/GD32W 等逐步扩展。
- 工程形态：寄存器裸机、标准库、HAL、LL、STM32CubeMX 生成工程、GD32 官方库工程。
- 运行形态：裸机主循环、事件驱动、FreeRTOS、RT-Thread、uCOS、ThreadX 等。
- 构建内容：应用源码、启动文件、链接脚本、HAL/StdPeriph 驱动、CMSIS、RTOS、第三方库。
- 调试烧录：ST-Link、CMSIS-DAP、J-Link、DAPLink、pyOCD、OpenOCD、厂商工具链后端。

实现策略：

- 核心解析器保持通用，只负责从 Keil 工程提取事实。
- 芯片差异进入 device database。
- 厂商差异进入 adapter。
- 烧录器差异进入 probe profile。
- 工程形态差异通过 project classifier 识别，例如 CubeMX、StdPeriph、裸机、RTOS。
- 不兼容点全部进入 diagnostics，不让用户靠猜。

这意味着 KeilBridge 不会把“通用”写成一堆硬编码 if，而是把信息拆成可维护的数据和插件式适配层。

## 15. 当前实现状态

已完成：

- 建立独立 `KeilTool` 目录。
- 创建 Python 包骨架。
- 创建 `k2c inspect` 和 `k2c model` CLI。
- 实现 `.uvprojx` 单 target 基础解析。
- 支持解析源码、include、define、library、startup、device、CPU 字段。
- 初步支持从 Keil CPU 字段推导 STM/GD vendor、family、core、FPU、float ABI、Flash/RAM。
- 已用 `HS_STEP_42C.uvprojx` 验证：识别 53 个源文件、16 个 include、6 个宏、1 个库、1 个 startup，识别 `STM32G431CBUx / stm32g4 / cortex-m4 / hard-float / 128K Flash / 32K RAM`。
- 增加第一版 diagnostics：可识别 Keil/ARMCC 专有宏、ARMCC `.lib`、疑似 ARMASM startup、缺失 ScatterFile。
- 增加第一版设备数据库：已包含 `STM32G431CBUx` 和一个 GD32F303 示例条目。
- `inspect` 已能显示设备数据库命中状态和 OpenOCD target。
- 增加 scatter 自动发现：当 `.uvprojx` 没有显式 ScatterFile 时，可在 Keil 工程目录下寻找 `.sct` 候选。
- 增加 `k2c scatter`：可解析 Keil `.sct` 并预览 GNU ld 脚本。
- 工具英文名确定为 **KeilBridge**，CLI 短命令继续使用 `k2c`。
- 增加 `configure` 命令：默认在目标 Keil 工程根目录生成 `.keilbridge/generated` 外部 CMake/OpenOCD/VS Code 工作区，避免多个工程互相覆盖。
- 增加 GCC startup 生成：从 Keil ARMASM startup 抽取向量表并生成 GNU as `.S`。
- 明确源码边界：KeilBridge 不修改、不替换、不自动修复用户源码；用户代码存在语法错误时，CMake/GCC 应正常报错。
- 增加最小 CMSIS-DSP 兼容层和 newlib syscalls 支持源。
- 增加 `build` 命令：可自动发现 VS CMake/Ninja 和 Arm GNU Toolchain。
- 已真实构建 `HS_STEP_42C`：生成 `elf/hex/bin/map`，Flash 约 36.48%，RAM 约 76.73%。
- `HS_STEP_42C` 当前能通过，是因为没有直接链接 ARMCC `DSP_LIB/arm_cortexM4lf_math.lib`，且最小 CMSIS-DSP 兼容层覆盖了当前用到的符号；这不代表 ARMCC CMSIS-DSP 库已被完整替换。
- 增加 `openocd` 命令和 VS Code Cortex-Debug 配置生成；当前机器未发现 `openocd.exe`，可通过 `--openocd` 显式传入。

下一步：

- 增加 OpenOCD 路径发现范围，例如 STM32CubeIDE、xPack OpenOCD。
- 增加 `flash` 命令，直接调用 OpenOCD program/verify/reset。
- 增加 `debug` 命令，可启动 OpenOCD server 或生成一键调试入口。
- 增加 project classifier，用于识别 CubeMX、标准库、裸机、RTOS 等工程形态。

## 16. 参考适配性注意事项后的补充原则

用户提供的《0侵入式Keil转CMake工具适配性注意事项》不作为逐字实现规范，但其中几个工程化原则已经纳入 KeilBridge：

- 必须先生成中间模型 IR，再由 generator 生成 CMake/OpenOCD/VS Code 文件，避免直接把 Keil XML 结构写死进 CMake。
- 解析层只提取事实：target、source、include、define、library、startup、scatter、device、CPU、工程形态。
- 兼容层必须有明确诊断：ARMCC 专有宏、ARMCC `.lib`、ARMASM startup、缺失 scatter、RTOS port、GD OpenOCD 未验证等。
- 路径解析必须支持 Keil 相对路径、Windows 反斜杠、空格、中文路径、环境变量、`$PROJ_DIR$` / `$(PROJ_DIR)` 这类工程宏。
- 芯片适配不能只靠硬编码，短期用内置 seed database，长期接入 CMSIS-Pack、厂商 pack、OpenOCD/J-Link/pyOCD 数据和用户 override。
- CubeMX 工程不重新生成代码，只复用 `.ioc` 旁边的 Core/Drivers/Middlewares 和 Keil 已选文件，不触碰 `USER CODE` 区域。
- RTOS 工程先识别和报告风险，再做明确的 port 映射；例如 FreeRTOS 的 RVDS/ARMCC portable layer 不能假装等价于 GCC port。
- 每次 `configure` 生成 `reports/project_ir.json` 和 `reports/conversion_report.md`，后续验证 GD、CubeMX、RTOS 都以报告为入口。

## 17. CubeMX / RTOS / GD32 当前边界

### CubeMX

当前支持状态：**识别 + 复用**。

KeilBridge 可以识别 `.ioc` 和 STM32 HAL/CubeMX 常见目录结构，生成外部 CMake 时复用 Keil 工程里已经列出的源文件、include、define。工具不会调用 CubeMX，不会改 `.ioc`，不会移动 Core/Drivers/Middlewares。

当前不承诺：自动处理所有 CubeMX 中间件组合、自动补齐未被 Keil target 选中的文件、自动重写 CubeMX 生成逻辑。

### RTOS

当前支持状态：**识别 + 诊断 + FreeRTOS RVDS/ARMCC 到 GCC port 的首个映射**。

KeilBridge 已开始识别 FreeRTOS、RT-Thread、ThreadX、uCOS 等工程形态，并在报告中提示 RTOS port 风险。GD32F303 验证工程中，Keil target 使用 FreeRTOS `portable/RVDS/ARM_CM4F`，外部 GCC 构建已映射到 `portable/GCC/ARM_CM4F`，原 Keil 工程和源码目录保持不变。后续完整支持仍需要逐个 RTOS 做 adapter，并检查 heap 文件是否重复。

当前不承诺：自动解决堆实现冲突、自动处理所有 BSP/中间件组合、自动修复用户 RTOS 配置错误。

### GD32

当前支持状态：**设备数据库 seed + 工程形态识别 + GD32F303CB/DAPLink/OpenOCD 实板验证**。

已加入 GD32F1/F3/F4/E2/L2 的少量 seed 条目，用来打通 parser、CMake 参数、内存模型和调试配置生成流程。GD32F303CB 已用 DAPLink/CMSIS-DAP 和 OpenOCD `stm32f3x.cfg` 兼容 target 完成编译、下载、verify、GDB 断到 `main`、运行到 FreeRTOS idle 的首个闭环验证。其他 GD 系列在未确认 OpenOCD target 前仍只生成诊断，不做“已支持”的虚假承诺。

下一步需要继续收集 GD32F1/F4/E/L 等真实板卡，用同一套流程跑 `inspect -> configure -> build -> openocd -> gdb`，再把成功/失败结果沉淀回设备数据库和 adapter。

## 18. VS Code 调试工作区规划

`configure/build/openocd` 打通以后，KeilBridge 还必须把 VS Code 调试体验当成独立功能处理，不能简单让用户打开 `.keilbridge/generated` 目录。

### 18.1 问题边界

- Keil 工程文件常在 `MDK-ARM`、`Keil5_project` 这类子目录，真实源码可能分散在上级 `Firmware`、`Drivers`、`Freertos`、`User`、`USP`、`Utilities` 等目录。
- 只打开 `generated` 会看不到完整源码，用户无法自然地在原始 `.c/.h` 文件中下断点。
- 多根 VS Code 工作区中 `${workspaceFolder}` 会随当前文件根目录变化，OpenOCD cfg、ELF、cwd 如果使用相对路径，容易导致 GDB server 启动失败。
- IntelliSense 不能手写一份 includePath，必须跟随 CMake 生成的 `compile_commands.json`，否则和真实 GCC 构建漂移。
- 生成的兼容源必须按需存在；不需要 CMSIS-DSP 时不能残留 `arm_math_compat.c` 让 C/C++ 插件报 `arm_math.h` 错误。

### 18.2 目标体验

- 用户打开 `.keilbridge/KeilBridge_<target>.code-workspace`，而不是打开 generated 文件夹。
- 工作区至少包含两个根：
  - `Original Source`：从 source/include 共同祖先推导出的完整源码根。
  - `KeilBridge Generated`：CMake、linker、startup、OpenOCD、报告等生成层。
- 用户在 `Original Source` 里的原始源码下断点。
- 调试配置、构建任务、C/C++ 设置写入 `.code-workspace` 顶层，避免 VS Code 多根目录解析歧义。
- launch 中关键路径全部使用绝对路径：
  - `executable`
  - `cwd`
  - `serverpath`
  - `searchDir`
  - `configFiles`
- tasks 中直接使用已发现的 CMake/Ninja/Arm GNU Toolchain 路径，保证换电脑时可通过重新 `configure` 再生成。

### 18.3 当前实现策略

- 从 target 的所有源文件目录和 include 目录计算公共祖先，作为 `Original Source`。
- 顶层 `.code-workspace` 写入 `launch.configurations` 和 `tasks.tasks`。
- `C_Cpp.default.compileCommands` 指向 `.keilbridge/build/gcc-debug/compile_commands.json`。
- 对 GD32F303 + DAPLink，生成工程专属 OpenOCD cfg，实测使用 `cmsis-dap.cfg + stm32f3x.cfg` 可连接、下载、verify。
- 生成层保留 `.vscode/launch.json` 作为兼容入口，但推荐入口是 `.code-workspace`。

### 18.4 验收标准

- VS Code 左侧能看到完整源码树，而不是只有局部 Keil 工程目录或 generated 目录。
- 在原始源码文件中设置断点，Cortex-Debug 能加载同一个 ELF 并命中源码路径。
- `OpenOCD: GDB Server Quit Unexpectedly` 不能由路径解析错误导致；如果 OpenOCD 仍失败，终端输出必须指向真实硬件/驱动/OpenOCD target 问题。
- 不需要的 generated support 源不会被 C/C++ 插件扫描出 include 错误。
- 重新 `configure` 后，VS Code 工作区能适配当前电脑上的工具链路径。

## 19. GD32F303 首次实板 Fault 复盘

### 19.1 现象

GD32F303CB 验证工程在初次生成的 GCC 固件中先进入 `MemManage_Handler`，修复启动向量后又进入 `HardFault_Handler`。这类问题必须优先按“工具生成错误”排查，不能把责任直接推给用户源码。

### 19.2 根因

- ARMASM startup 里存在 `__Vectors DCD __initial_sp` 这种“标签和 DCD 同行”的写法，早期解析器没有识别，导致生成的 GCC 向量表首项被误写成 Reset_Handler 地址，而不是初始 MSP。
- Keil output 目录里残留了 `motor.sct`，其中 RAM 为 48K；当前 target `GD32F303CB` 的 Cpu/device memory 是 32K。早期生成器把候选 scatter 当成事实来源，导致 `_estack = 0x2000c000`，超出真实 RAM 顶部 `0x20008000`，启动或任务切换后触发 Fault。

### 19.3 修复原则

- 向量表第 0 项必须强制生成 `_estack`，不依赖 ARMASM 原符号名。
- 只有 Keil target 显式配置了 `ScatterFile`，才把该 scatter 作为链接事实来源。
- 未显式配置 scatter 时，优先使用当前 target 的 Cpu/device memory。
- 自动发现的 `.sct` 只能作为诊断候选；如果候选内存和当前 target 不一致，报告 `scatter_candidate_memory_mismatch`，不能静默使用。

### 19.4 当前验证结果

- CMake/GCC 构建通过，链接内存为 `FLASH 128K`、`RAM 32K`。
- ELF `.isr_vector` 首项为 `0x20008000`，Reset 向量为 `Reset_Handler`。
- OpenOCD 通过 DAPLink/CMSIS-DAP 连接 `GD32F303CB`，下载和 verify 通过。
- 板子 reset run 运行 2 秒后 halt，PC 位于 `Freertos/Source/tasks.c` 的 `prvIdleTask`，没有立即进入 HardFault。
- GDB 可连接 OpenOCD，`monitor reset halt` 后硬件断点命中原始源码 `Template/main.c:25`。

## 20. 需求收敛与技术路线再定义

结合新增的需求分析、Doctor 设计、已有工具链分析和工具化开发 SOP，KeilBridge 的定位需要从“Keil 转 CMake 小工具”升级为：

> 面向 Keil 遗留工程的零侵入桥接、诊断和调试可观测工具。

这意味着 CMake/GCC 只是一个重要后端，不是最终目的。真正要解决的痛点是：Keil 工程中的构建、烧录、调试、变量、寄存器、调用栈、Fault 现场等信息过去只能靠用户手动转述，现在要变成脚本可执行、结果可保存、AI 可读取、问题可诊断的结构化流程。

### 20.1 真实需求

一句话真实需求：

> 把 Keil 工程的构建、下载、复位、断点、变量、寄存器、内存、调用栈和 Fault 现场采集，变成零侵入、可重复、可结构化输出的自动化流程，减少用户在 IDE、硬件和 AI 之间手工搬运信息的成本。

因此，KeilBridge 不承诺“任何 Keil 工程都 0 成本转 GCC”。更准确的承诺是：

- 能自动桥接的工程，自动生成 CMake/GCC/OpenOCD/VS Code 工作区。
- 能诊断的问题，输出 KeilBridge 诊断结论，而不是只甩出 GCC/OpenOCD 原始报错。
- 能安全兼容的问题，生成 compat header、generated support 或 overlay 副本，原工程不动。
- 需要人工确认的问题，生成 patch/report/override 模板，不擅自修改用户源码。
- GCC 后端遇到硬边界时，明确推荐 ArmClang、Keil CLI 或用户提供 GCC `.a`/源码重编译路线。

### 20.2 不照抄参考文档的边界

新增文档中的原则作为路线参考，但不逐字照做。当前项目按真实验证结果推进：

- 已经跑通的 STM32G4、GD32F303、STM32F405 + FreeRTOS 经验优先进入实现。
- 先保证一个工程从 `inspect -> configure -> build -> flash -> debug` 闭环稳定，再扩展芯片数量。
- 先输出报告和诊断，再做自动修复。
- 先复用 CMake、Ninja、GDB、OpenOCD、J-Link、pyOCD、Cortex-Debug、Keil CLI 等成熟工具，再自研桥接层和诊断层。
- 不把“通用”写成大量硬编码 `if device contains ...`，芯片、探针、RTOS、库兼容进入数据库、adapter 和 doctor 规则。

### 20.3 技术路线

KeilBridge 的主流程调整为：

```text
Keil 工程
  ↓
Project Scanner：读取 .uvprojx/.uvoptx/.sct/.ioc/源码线索
  ↓
Project IR：生成 project_ir.json，保留事实和证据
  ↓
Adapter Registry：解释 STM32/GD32/CubeMX/StdPeriph/RTOS/裸机差异
  ↓
Doctor Engine：scan/build/elf/flash/debug/compat/lib 分阶段诊断
  ↓
Generator：生成 CMake、linker、startup、OpenOCD、VS Code、报告
  ↓
Backend：GCC / ArmClang / Keil CLI / OpenOCD / J-Link / pyOCD / GDB
  ↓
Structured Result：doctor_result.json、debug_result.json、fault_dump.md
```

职责边界：

- Scanner 只发现事实，不做主观修复。
- Adapter 负责解释事实，例如 CubeMX、GD 标准库、FreeRTOS port、CMSIS-DSP。
- Doctor 负责判断风险、阻塞点和下一步建议。
- Generator 只根据 IR 和 adapter 结果生成外部工作区。
- Backend 负责调用已有工具，不自研编译器、调试协议或烧录器。

### 20.4 Doctor 系统成为一等功能

后续命令不只围绕 `configure/build/flash/debug`，还要增加 Doctor 子命令：

```powershell
python -m keiltool.cli doctor scan  --project <uvprojx> --target <target>
python -m keiltool.cli doctor build --project <uvprojx> --target <target>
python -m keiltool.cli doctor elf   --project <uvprojx> --target <target>
python -m keiltool.cli doctor flash --project <uvprojx> --target <target> --probe cmsis-dap
python -m keiltool.cli doctor debug --project <uvprojx> --target <target> --probe cmsis-dap
python -m keiltool.cli doctor all   --project <uvprojx> --target <target>
```

Doctor 优先级：

1. Build Doctor：把 include 缺失、宏缺失、ARMASM startup、RTOS port、`.lib`、FPU ABI 等构建失败分类。
2. ELF Doctor：检查 `.isr_vector`、`Reset_Handler`、`_estack`、Flash/RAM 段地址、map/size 和 bootloader offset。
3. Flash Doctor：检查 OpenOCD/J-Link 路径、interface/target cfg、探针占用、芯片 ID、program/verify 结果。
4. Debug Doctor：先 `reset halt`、读寄存器和向量表，确认 MSP/PC 合法后再断到 `main`，失败时输出 `fault_dump.md`。
5. Compat Doctor：扫描 ARMCC 专用语法，分为兼容头可处理、生成 patch、必须人工处理三类。
6. Lib Doctor：识别 ARMCC `.lib`、GCC `.a`、源码替代和 C++ ABI 风险，输出后端兼容矩阵。

### 20.5 后端策略

GCC 后端继续作为第一条主线，因为它开放、适合 CMake/Ninja/CI/GDB 自动化。但 KeilBridge 不能把 GCC 当成唯一答案。

后端分层：

- `gcc`：默认后端，生成 CMake + arm-none-eabi-gcc。
- `armclang`：未来后端，用于降低 Keil/ARMCC 迁移成本，尤其是复杂 scatter、ARM 生态库和编译器扩展。
- `keil`：保底后端，通过 Keil CLI 构建/下载，用于闭源 `.lib` 或短期无法迁移工程。
- `debug-only`：输入已有 ELF/AXF，不做 CMake 转换，只做 flash/debug/doctor/fault dump。

这条 `debug-only` 路线很重要。它可以先解决“AI 看不到调试现场”的真实痛点，即使某个工程暂时不能 GCC 化，也仍然能让 KeilBridge 采集寄存器、变量、调用栈和 Fault 现场。

### 20.6 用户覆盖与换电脑

自动识别永远会有边界，因此必须支持用户覆盖文件：

```text
<project-root>/.keilbridge/keilbridge.yaml
<project-root>/.keilbridge/board.override.yaml
<project-root>/.keilbridge/generated/board.override.template.yaml
```

覆盖项包括：

- device/vendor/family/part/core/fpu/float ABI
- flash/ram/ccmram/app offset/vector table origin
- startup/linker 优先项
- probe/backend/openocd/jlink/pyocd 配置
- 工具链路径、OpenOCD 路径、脚本路径
- `.lib` 替代 `.a`、源码替代目录、CMSIS-DSP 根目录

换电脑时的原则：

- `.keilbridge/generated` 和 `.keilbridge/build` 可以删除并重新生成。
- 原工程和 Keil 配置不依赖 KeilBridge。
- 用户只需要保留可编辑 override 和必要的工具链路径配置。
- `configure` 必须重新探测当前电脑上的 CMake、Ninja、Arm GNU Toolchain、OpenOCD/J-Link 路径，并刷新 VS Code workspace。

### 20.7 近期开发顺序调整

下一阶段不再单纯追求“多支持几个芯片型号”，而是围绕已经暴露的真实问题补齐可观测闭环：

1. 把当前 `inspect/configure/build/flash/debug` 的关键结果写入 `.keilbridge/report/project_ir.json`、`conversion_report.md`。
2. 实现 Build Doctor 规则库，优先覆盖当前遇到的 `.lib`、startup、FreeRTOS port、include、FPU ABI、undefined reference。
3. 实现 ELF Doctor，自动检查向量表、Reset_Handler、_estack、Flash/RAM 段地址，避免再次出现“编译过了但复位进 Fault”。
4. 实现 Flash Doctor，识别 ESP-IDF OpenOCD 用于 STM/GD 的风险、DAPLink/CMSIS-DAP 占用、program/verify 失败原因。
5. 实现 Debug Doctor 最小闭环：连接、halt、reset halt、读 MSP/PC/VTOR、断 main、读寄存器、输出 `debug_result.json`。
6. 再扩展 GD32/STM32 设备数据库和 OpenOCD/J-Link 映射。
7. 最后推进 ArmClang/Keil CLI 后端，让闭源 `.lib` 工程也能进入脚本化流程。

### 20.8 成功标准

一个工程真正“适配成功”不只看是否生成 CMake，而要同时满足：

- 原工程 0 修改，`.uvprojx/.uvoptx/.sct/.ioc/.c/.h` 不被改动。
- `.keilbridge` 内生成物可删除、可重建、可跨电脑重新配置。
- `build` 能生成 elf/hex/bin/map，或 Doctor 明确说明阻塞原因。
- `flash` 能 program/verify/reset，或 Doctor 明确定位到探针、OpenOCD、target cfg、芯片连接问题。
- `debug` 能断到原始源码 `main`，或 Debug Doctor 输出 PC/MSP/VTOR/Fault 现场。
- 用户能在 VS Code 中看到完整原始源码并下断点，不被 generated 目录困住。
- 对 `.lib`、RTOS、ARMCC 语法、CubeMX 中间件等硬边界，报告说清楚“为什么不行、下一步怎么办”。

## 21. 架构与 ArmClang 后端规划

新增文档里关于架构的核心判断是正确的：KeilBridge 不能继续把复杂度堆进 CMake 生成器，而要形成 `IR + Adapter + Doctor + Backend` 的平台结构。

### 21.1 架构判断

当前最需要避免的写法是：

```text
cmake_generator.py:
  if STM32G4 ...
  if GD32F30x ...
  if FreeRTOS ...
  if ARMCC .lib ...
  if startup is ARMASM ...
```

这会让短期样例能跑，但后续每加一个芯片、RTOS、烧录器、库类型都会污染 CMake generator。正确边界应该是：

- Parser：只解析 Keil 工程事实，不解释业务含义。
- Project IR：保存 source/include/define/library/startup/scatter/device/feature/evidence。
- Adapter：解释 STM32/GD32/CubeMX/StdPeriph/RTOS/CMSIS-DSP 等工程差异。
- Doctor：判断风险、失败原因和下一步建议。
- Generator：只根据 IR 和 Adapter 结果生成 CMake、linker、startup、VS Code、OpenOCD。
- Backend：调用 GCC、ArmClang、Keil CLI、OpenOCD、J-Link、pyOCD、GDB。

### 21.2 后端能力矩阵

KeilBridge 后续要给每个工程输出后端兼容矩阵，而不是只说“转换失败”：

```text
Backend       Build       Flash/Debug       适用场景
------------------------------------------------------------
gcc           preferred   preferred         开放构建、CI、GDB 自动化
armclang      planned     possible          降低 Keil/ARMCC 工程迁移成本
keil          fallback    limited/scripted  闭源 .lib 或短期不能迁移的工程
debug-only    none        preferred         已有 ELF/AXF，只采集调试现场
```

这套矩阵必须由 Doctor 和 Lib Resolver 共同生成。例如检测到 ARMCC `.lib` 时，GCC 后端应标记 `blocked`，ArmClang 标记 `maybe` 或 `unknown`，Keil 后端标记 `supported`。

### 21.3 ArmClang 的定位

ArmClang 非常值得适配，但它不是 GCC 的替代主线，也不是万能兼容层。它的定位是：

> 面向 Keil 遗留工程的兼容后端，用来降低 ARMCC 语法、scatter、ARM 生态库和 Keil 工程习惯带来的迁移成本。

适合优先尝试 ArmClang 的场景：

- 工程依赖 ARMCC/ArmClang 风格 section、pragma、attribute。
- scatter 文件复杂，直接转换 GNU ld 风险高。
- 有 ARM 生态库或厂商提供的 ArmClang 兼容库。
- 用户想脱离 Keil GUI，但不急着切到 GCC。
- CMake/GDB/OpenOCD 脚本化比编译器替换更重要。

必须明确的边界：

- ARMCC5 `.lib` 不保证能被 ArmClang 无痛链接。
- C++ ABI、异常、运行库、microlib/newlib/semihosting 差异要单独诊断。
- ArmClang 安装、授权、Keil 环境变量、Pack 依赖比 GCC 更复杂。
- ArmClang 生成的 ELF/AXF 是否适合 GDB/OpenOCD 调试，需要真实工程 Spike 验证。

### 21.4 ArmClang 实施顺序

ArmClang 不立即进入大规模开发，先按 Spike 推进：

1. 增加 Backend capability 数据结构，先让报告能表达 `gcc/armclang/keil/debug-only` 的状态。
2. 增加 Lib Doctor，遇到 `.lib` 时输出后端兼容矩阵。
3. 增加 `debug-only`，允许用户输入 Keil 已生成的 AXF/ELF，先做 OpenOCD/J-Link/GDB 调试采集。
4. 做 ArmClang 最小 Spike：一个 STM32 工程、一个 GD 工程，只验证编译、链接、生成 ELF/AXF。
5. 再实现正式 `--backend armclang`，生成对应 CMake toolchain、compile flags、link flags 和 scatter 使用策略。

短期实现仍以 GCC + Doctor 闭环为主。ArmClang 的价值要通过 Doctor 推荐出来，而不是用口号承诺所有 Keil 工程都能自动迁移。

### 21.5 当前 Sentry_gimbal 调试失败复盘入口

`Sentry_gimbal` 当前 VS Code/Cortex-Debug 失败时，生成配置已满足：

- `configFiles` 使用绝对路径。
- `executable` 使用 `.keilbridge/build/gcc-debug/Sentry_gimbal.elf`。
- `loadFiles: []` 已阻止 Cortex-Debug 通过 GDB 再次下载 ELF。
- 工作区已经同时包含原始源码和 generated 目录。

本地 OpenOCD 日志显示的失败点是：

```text
Error: error writing data: hid_write/WaitForSingleObject: (0x000003E5)
Error: CMSIS-DAP command CMD_INFO failed.
```

这类问题应归入 Flash/Debug Doctor，而不是继续让用户猜。Doctor 需要给出：

- 当前使用的是 ESP-IDF OpenOCD，目标却是 STM32F405，存在版本/打包风险。
- CMSIS-DAP/DAPLink HID 访问失败，优先检查 VS Code 旧 OpenOCD 进程、串口监视器、其他调试器、驱动状态和重新插拔。
- 如果复现失败，保存 OpenOCD stdout/stderr 到 `.keilbridge/logs/`，并输出可复制的重试命令。

### 21.6 Sentry_gimbal `.CCM` 段复盘

`Sentry_gimbal` 修复烧录和 reset vector 后，程序进入 `SRML/Drivers/Components/drv_can.c` 的静态 `Error_Handler`。GDB 调用栈显示：

```text
Error_Handler()
CAN_Init(hcan=&hcan1, pFunc=User_CAN1_RxCpltCallback)
System_Device_Init()
main()
```

失败点位于 `CAN_Init()` 末尾：`hcan1.Instance` 没有匹配 `CAN_Instances[]`。根因不是业务 CAN 配置，而是 KeilBridge 生成层漏处理了 Keil scatter 中的 `RW_CCM` / `.CCM` 段。

原工程中存在：

```text
RW_CCM 0x10000000 0x00010000
  *(.CCM)
```

SRML 又把若干外设实例表放进 `.CCM`：

```c
__CCM const CAN_TypeDef* CAN_Instances[CAN_NUM] = {CAN1, CAN2};
```

早期 GNU ld 脚本没有生成 `CCMRAM` 区域，也没有把 `*(.CCM*)` 放入可初始化段；startup 也只复制 `.data`，没有复制 `.CCM`。结果是 `.CCM` 中的初始化数据没有按 Keil 语义搬运，运行时 `CAN_Instances[]` 内容不可信，导致 `CAN_Init()` 误判并进入 `Error_Handler`。

修复原则：

- scatter parser 必须把 `RW_CCM` 识别为独立 `CCMRAM`。
- GNU ld 脚本必须生成 `.ccmram`，收集 `*(.CCM)` 和 `*(.CCM*)`，并设置 `AT> FLASH`。
- startup 必须在复制 `.data` 后复制 `.CCM` 初始化数据。
- 没有 CCMRAM 的工程仍定义空的 `_sccm/_eccm/_siccm`，保持 startup 模板通用。

当前验证结果：

- `Sentry_gimbal` 重新构建后链接报告显示 `CCMRAM: 432 B`。
- OpenOCD program/verify 成功。
- GDB 已能断到 `main()`。
- 对所有 `Error_Handler` 下断点后运行，未再命中原来的 `CAN_Init()` 错误路径。

### 21.7 Sentry 24 C++ 兼容性复盘

`24-Sentry-Gimbal` 工程验证时，GCC C++ 编译在 `board_com.h` 阻塞：

```text
declaration of 'sentry_type BoardCom_Classdef::sentry_type' changes meaning of 'sentry_type'
```

源码里先定义了 typedef：

```c
typedef enum sentry_type { ... } sentry_type;
```

随后在 C++ class 中又定义了同名成员：

```cpp
sentry_type sentry_type;
```

Keil/ArmClang 遗留工程里常见这种较宽松的 C++ 写法。G++ 默认把它视为错误，但 `-fpermissive` 可以降级为 warning。KeilBridge 的处理原则：

- 不修改用户源码。
- 不生成源码 patch。
- 仅对 C++ 编译单元增加 `-fpermissive`。
- 把这类问题归入 Compat/Build Doctor 的“编译器严格性差异”，后续报告中提示。

当前验证结果：

- `24-Sentry-Gimbal` 已完成 configure/build。
- 构建生成 `Template.elf/hex/bin/map`。
- 链接报告显示 `FLASH 8.26%`、`RAM 82.87%`、`CCMRAM 0.56%`。
- `.CCM` 段支持在 24/25 两个 Sentry 工程中均已验证。

### 21.8 `flash` 子命令闭环验证

`doctor flash --run` 的职责是诊断 OpenOCD/探针/复位向量，不负责真正下载固件。为避免用户误以为 Doctor 已经完成烧录，KeilBridge 新增独立命令：

```powershell
python -m keiltool.cli flash --project "<project.uvprojx>" --target "<target>" --probe cmsis-dap
```

实现边界：

- `flash` 默认查找 `.keilbridge/build/gcc-debug/<target>.elf`。
- `flash` 默认使用 `.keilbridge/generated/openocd/<target>_<probe>.cfg`。
- 命令内部调用 OpenOCD `program <elf> verify reset exit`，成功标准是 OpenOCD 返回 0 且出现 `Programming Finished`、`Verified OK`。
- 该命令会真实覆盖芯片 Flash，因此应与 Doctor 明确分离。

本次修复记录：

- 首次执行 `flash` 暴露 CLI 内部 bug：`NameError: name '_sanitize_name' is not defined`。
- 根因是 `configure/build` 生成层已有 Target 名规范化函数，但 `flash` 子命令查找产物时没有同规则函数。
- 已在 CLI 层补齐 `_sanitize_name()`，并用中文注释说明它必须与 generator/workspace 层保持一致。
- `24-Sentry-Gimbal` / `Template` / `cmsis-dap` 已完成实机下载验证，OpenOCD 输出 `Programming Finished` 和 `Verified OK`。

### 21.9 CMSIS-DAP 烧录中途命令错位

`24-Sentry-Gimbal` 后续再次执行 `flash` 时，OpenOCD 已识别 STM32F405 并进入 program 阶段，但烧录中途失败：

```text
Error: CMSIS-DAP command mismatch. Sent 0x11 received 0x5
Error: CMSIS-DAP command CMD_DAP_SWJ_CLOCK failed.
Error: Failed to write memory at 0x20001a58
Error: error writing to flash at address 0x08000000 at offset 0x00000000
** Programming Failed **
```

这类错误应归入 Flash Doctor 的探针/OpenOCD 通信层，而不是归咎于 CMake、ELF 或用户源码。关键判断依据：

- OpenOCD 能读到 SWD DPIDR。
- OpenOCD 能识别 Cortex-M4 和 STM32F405 flash size。
- 失败发生在 program 阶段的 CMSIS-DAP 命令响应。
- 当前 OpenOCD 仍来自 ESP-IDF 打包版本，存在用于 STM32/GD32 的兼容性风险。

已纳入工具规则：

- 新增 `CMSIS_DAP_COMMAND_MISMATCH` 诊断。
- 新增 `OPENOCD_FLASH_WRITE_FAILED` 诊断。
- `flash` 命令失败时保存 stdout/stderr 到 `.keilbridge/logs/`。
- `flash` 命令失败时直接调用 Doctor 分类规则并打印可读建议。

建议动作顺序：

1. 结束残留 `openocd.exe`、`arm-none-eabi-gdb.exe`、VS Code gdb-server。
2. 关闭串口监视器和其他占用 DAPLink 的软件。
3. 重新插拔 DAPLink。
4. 重新执行 `doctor flash --run`。
5. 再执行 `flash`。
6. 若仍复现，优先切换到 xPack OpenOCD、STM32CubeCLT OpenOCD 或系统独立 OpenOCD。

### 21.10 VS Code preLaunchTask 不应依赖 PATH

`24-Sentry-Gimbal` 调试时出现 VS Code 弹窗：

```text
preLaunchTask "CMake: build" 已终止，退出代码为 1
cmake: 无法将 "cmake" 项识别为 cmdlet、函数、脚本文件或可运行程序的名称
```

根因不是工程编译失败，而是 generated 目录里的 legacy `.vscode/tasks.json` 仍使用：

```text
cmake --preset gcc-debug
cmake --build --preset gcc-debug
```

VS Code task 的 PowerShell 环境不一定继承命令行 PATH，因此找不到 `cmake.exe`。虽然 `.code-workspace` 已使用绝对路径任务，但用户如果从 generated 配置启动调试，仍会触发旧 `CMake: build`。

修复原则：

- generated `.vscode/launch.json` 和 `.code-workspace` 均使用 `preLaunchTask: KeilBridge: build`。
- generated `.vscode/tasks.json` 和 `.code-workspace` 均使用同一套 `process` task。
- task 的 `command` 使用 KeilBridge 探测到的绝对 `cmake.exe`。
- Ninja 通过 `-DCMAKE_MAKE_PROGRAM=<absolute ninja.exe>` 固定。
- `ARM_GCC_ROOT` 写入 task env，避免 VS Code task 环境找不到交叉编译器。

验证结果：

- 重新 `configure` 后，`24-Sentry-Gimbal` 的 generated 和 code-workspace 均不再包含旧 `CMake: build`。
- `preLaunchTask` 已更新为 `KeilBridge: build`。
- 命令行重新 `build` 通过。

### 21.11 C++ 全局对象构造缺失导致 HardFault

`24-Sentry-Gimbal` 进入 FreeRTOS 后卡在 `HardFault_Handler`。通过 OpenOCD telnet 读取现场：

```text
CFSR = 0x00000100
HFSR = 0x40000000
PC   = 0x08007de6  // HardFault_Handler
LR   = 0xffffffed
PSP  = 0x20009668
```

解析 PSP 栈帧后，异常前 PC 为 `0x20020000`，LR 反查到：

```text
AttitudeAlgorithm_Classdef::update_deg(...)
USP/Middlewares/attitudeAlgorithm.cpp:58
```

反汇编显示 `update_deg()` 通过虚表调用 `update_rad()`：

```text
ldr r3, [r0, #0]
ldr r3, [r3, #0]
blx r3
```

`r0(this)` 指向全局对象 `attitudeAlgorithm`。读取对象内存发现其虚表指针为 `0x00000000`，说明该全局 C++ 对象只被 BSS 清零，构造函数没有执行。根因是：

- startup 已调用 `__libc_init_array()`。
- 但 GNU ld 脚本没有保留 `.preinit_array/.init_array/.fini_array/.ctors/.dtors`。
- 因此 `__libc_init_array()` 没有构造函数表可遍历。
- 带虚函数、默认成员初始化的全局 C++ 对象不会被正确构造。

修复：

- GNU ld 脚本新增 `.preinit_array`、`.init_array`、`.fini_array`、`.ctors`、`.dtors`。
- 使用 `KEEP(*(SORT(.init_array.*)))` 和 `KEEP(*(.init_array*))` 防止构造入口被 gc-sections 丢弃。
- 添加测试 `tests/test_linker_generation.py`，确保链接脚本持续保留 C++ 构造段。

验证：

- 重新 `configure/build/flash` 后，ELF 出现 `__init_array_start/end` 和多个 `_GLOBAL__sub_I_...`。
- 到达 `main` 时读取 `attitudeAlgorithm`，首字为 `0x08019d64`，对应 `vtable for AttitudeAlgorithm_Classdef` 附近地址。
- 下 `HardFault_Handler` 断点运行 5 秒未命中。
- Fault 状态寄存器恢复为 `CFSR=0x00000000`、`HFSR=0x00000000`。

这条修复属于 KeilBridge 启动/链接层通用能力，不是 24Sentry 单工程特例。凡是 CubeMX + C++ + 全局对象/虚函数/默认成员初始化的工程，都依赖这条链路。

## 当前阶段补充：GCC / ArmClang 双后端路线

KeilBridge 后续不再把“Keil 转 CMake”简单理解成“全部强行转 GCC”。第一次创建工作区时，工具必须先扫描整个工程，再给用户推荐后端：

```powershell
python -m keiltool.cli doctor backend --project "<project.uvprojx>" --target "<target>"
```

当前后端边界：

- `gcc`：已经是当前可用主路线，负责 CMake、GNU ld、GCC startup、OpenOCD/VS Code 工作区。
- `armclang`：作为兼容迁移路线优先实现入口和诊断，完整 ArmLink/CMake 生成后续推进。
- `debug-only`：构建暂时无法迁移时，用已有 ELF/AXF 做调试和故障采集。
- `keil-cli`：保留 Keil 原构建语义的兜底路线。

新增配置语义：

```powershell
python -m keiltool.cli configure --project "<project.uvprojx>" --target "<target>" --backend auto
python -m keiltool.cli configure --project "<project.uvprojx>" --target "<target>" --backend gcc
python -m keiltool.cli configure --project "<project.uvprojx>" --target "<target>" --backend armclang
```

- `--backend auto`：只输出推荐报告，不生成工作区，让用户明确选择。
- `--backend gcc`：生成当前已验证的 GCC 工作区。
- `--backend armclang`：当前只保留选择入口和工具链诊断，完整生成器未启用前必须明确提示。
