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
