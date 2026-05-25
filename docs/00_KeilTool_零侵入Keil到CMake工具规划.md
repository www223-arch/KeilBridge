# KeilTool 零侵入 Keil 到 CMake 工具规划

## 1. 项目定位

KeilTool 是一个面向嵌入式工程的外部构建适配器。

它不把 Keil 工程“改造成” CMake 工程，而是在 Keil 工程外部生成一层现代构建、烧录、调试入口。

核心原则：

- 原 Keil 工程是唯一事实源。
- 不移动源码，不改目录结构，不修改 `.uvprojx/.uvoptx/.sct/.ioc`。
- 所有 CMake、VS Code、烧录、缓存、日志产物都放在 KeilTool 自己的工作区。
- Keil 能继续照常使用，CMake 只是并行构建入口。

一句话目标：

> 给现有 Keil 工程外挂一套可复现、可自动化、可扩展的 GCC/CMake 构建和调试系统。

## 2. 非目标

为了保持技术边界清晰，KeilTool 第一阶段不做这些事：

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
D:/GD32/GDproject/KeilTool/
  keiltool.yaml
  .keiltool/
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

目标 Keil 工程目录保持原样。

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

KeilTool 必须把“不兼容点”工具化，而不是甩给用户手动改。

### 7.1 Startup

Keil ARMASM `.s` 通常不能直接交给 GCC。

处理策略：

1. 优先在工程或芯片包中寻找 GCC 版 startup。
2. 找不到时，根据芯片型号和向量表模板生成 GCC startup。
3. 生成文件放入 `.keiltool/generated/startup/`。

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
- 用户可在 `keiltool.yaml` 中配置替代库路径。

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

`keiltool.yaml` 是用户可编辑配置，保存 override，不保存自动解析出来的大量清单。

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

1. 创建 KeilTool Python 项目骨架。
2. 实现 `k2c inspect <uvprojx>`，只解析并打印工程摘要。
3. 实现 `k2c model <uvprojx> --json`，输出中间模型。
4. 用 `HS_STEP_42C.uvprojx` 做第一条真实样例。
5. 再开始生成 CMake。

这样每一步都可验证，不会一开始就把所有问题混在一起。

## 14. 长期适配目标：STM/GD 全系列优先

KeilTool 的长期目标不是只服务某一个工程，而是形成一个可扩展的 Keil 外部构建适配平台。

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

这意味着 KeilTool 不会把“通用”写成一堆硬编码 if，而是把信息拆成可维护的数据和插件式适配层。

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

下一步：

- 将 scatter 转换结果真正写入 `.keiltool/generated/linker/`。
- 增加 `configure` 命令，生成外部 CMake 工作区。
- 增加 GCC startup 模板生成。
- 增加 project classifier，用于识别 CubeMX、标准库、裸机、RTOS 等工程形态。
