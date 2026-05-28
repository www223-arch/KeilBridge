# KeilBridge 用户使用手册

KeilBridge 用来把现有 Keil MDK 工程接入外部构建、诊断、烧录和 VS Code 调试流程。它默认不修改原工程，不移动源码，不改 `.uvprojx/.uvoptx/.ioc/.sct`，只在目标工程根目录生成 `.keilbridge/`。

## 1. 前置环境

### 1.1 公共前置

所有使用方式都需要：

- Windows PowerShell。
- Python 3.10 或更高版本。
- VS Code。
- VS Code 插件 `C/C++`，插件 ID：`ms-vscode.cpptools`。
- VS Code 插件 `Cortex-Debug`，插件 ID：`marus25.cortex-debug`。
- OpenOCD，推荐 xPack OpenOCD 或 STM32CubeCLT OpenOCD。
- Arm GNU Toolchain 中的 `arm-none-eabi-gdb.exe`。

建议把 KeilBridge 工具目录固定下来，执行命令前先进入：

```powershell
cd D:\GD32\GDproject\KeilTool
```

### 1.2 GCC/CMake 后端需要

如果使用 `--backend gcc`，还需要：

- CMake。
- Ninja。
- Arm GNU Toolchain 中的 `arm-none-eabi-gcc.exe`、`arm-none-eabi-objcopy.exe`、`arm-none-eabi-size.exe`。

这条路线会由 KeilBridge 生成独立 CMake 工程，并生成 `.elf/.hex/.bin/.map`。

### 1.3 ArmClang 后端需要

如果使用 `--backend armclang`，还需要：

- Keil MDK Arm Compiler 6。
- `armclang.exe`。
- `armlink.exe`。
- `fromelf.exe`。

如果工具不在常规路径，可以设置：

```powershell
$env:ARMCLANG_ROOT="C:\Keil_v5\ARM\ARMCLANG"
```

或在 build 时显式传入：

```powershell
python -m keiltool.cli build --project "C:\Path\To\App.uvprojx" --target App --backend armclang --armclang-root "C:\Keil_v5\ARM\ARMCLANG"
```

### 1.4 Debug-only 后端需要

如果使用 `--backend debug-only`，还需要：

- Keil MDK 能正常编译原工程。
- 已有 Keil 生成的 `.axf` 或 `.elf`。
- 该 `.axf/.elf` 带调试符号。

这条路线不编译、不下载固件，只用 Keil 产物做符号调试。

## 2. 推荐流程：先诊断，再选择

首次接入一个 Keil 工程时，推荐按下面顺序走。

### 2.1 查看工程信息

```powershell
python -m keiltool.cli inspect "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App -v
```

它会显示：

- 目标芯片、内核、FPU、内存。
- Keil target 名称。
- 源文件、include、define、startup、scatter。
- 是否检测到 CubeMX、RTOS、CMSIS-DSP、ARMCC `.lib` 等风险点。

如果不知道 target 名称，可以先不写 `--target`，或看报错中的 `Available targets`。

### 2.2 让系统推荐后端

```powershell
python -m keiltool.cli doctor backend --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App
```

它会评估：

- `gcc`：开放工具链、CMake/Ninja、CI 友好。
- `armclang`：更贴近 Keil/ArmLink 语义。
- `debug-only`：复用已有 Keil AXF/ELF，只做调试。
- `keil-cli`：保留 Keil 构建语义的兜底方向。

报告位置：

```text
<keil-project-root>\.keilbridge\generated\reports\backend_recommendation.md
<keil-project-root>\.keilbridge\generated\reports\backend_recommendation.json
```

### 2.3 只生成诊断报告，不生成工作区

```powershell
python -m keiltool.cli configure --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --backend auto
```

`auto` 不替用户强行选择后端，只写推荐报告。确认路线后，再显式指定后端。

## 3. 指定编译或调试方式

### 3.1 指定 GCC/CMake

```powershell
python -m keiltool.cli configure --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --backend gcc

python -m keiltool.cli build --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --backend gcc
```

产物位置：

```text
<keil-project-root>\.keilbridge\build\gcc-debug\App.elf
<keil-project-root>\.keilbridge\build\gcc-debug\App.hex
<keil-project-root>\.keilbridge\build\gcc-debug\App.bin
<keil-project-root>\.keilbridge\build\gcc-debug\App.map
```

### 3.2 指定 ArmClang

```powershell
python -m keiltool.cli configure --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --backend armclang

python -m keiltool.cli build --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --backend armclang
```

产物和工作区与 GCC 分开：

```text
<keil-project-root>\.keilbridge\generated\armclang\
<keil-project-root>\.keilbridge\build\armclang-debug\
<keil-project-root>\.keilbridge\KeilBridge_<target>_armclang.code-workspace
```

### 3.3 指定 Debug-only

```powershell
python -m keiltool.cli configure `
  --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" `
  --target App `
  --probe stlink `
  --backend debug-only `
  --elf "C:\Path\To\Project\MDK-ARM\App\App.axf"
```

工作区位置：

```text
<keil-project-root>\.keilbridge\KeilBridge_<target>_debug.code-workspace
```

Debug-only 工作区通常有两个入口：

- `KeilBridge Debug-only Attach (...)`：连接当前运行现场，不主动复位，不下载。
- `KeilBridge Debug-only Reset/Halt (...)`：不下载固件，但会复位并暂停。

## 4. 烧录和调试前诊断

### 4.1 Flash Doctor

```powershell
python -m keiltool.cli doctor flash --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --run
```

它会检查：

- OpenOCD 是否能启动。
- 探针是否能连接目标芯片。
- reset/halt 后 PC/MSP 是否像有效启动向量。
- 常见 OpenOCD、CMSIS-DAP、ST-Link 通信错误。

它不会下载固件。

报告位置：

```text
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_report.md
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_result.json
<keil-project-root>\.keilbridge\logs\
```

### 4.2 ELF Doctor

构建成功后建议运行：

```powershell
python -m keiltool.cli doctor elf --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App
```

它会检查：

- 启动段和向量表。
- `.data/.bss` 等 RAM 段风险。
- C++ 全局构造相关 `.init_array` 风险。
- FreeRTOS 常见入口符号风险。

报告位置：

```text
<keil-project-root>\.keilbridge\generated\reports\elf_doctor_report.md
<keil-project-root>\.keilbridge\generated\reports\elf_doctor_result.json
```

### 4.3 真正烧录

```powershell
python -m keiltool.cli flash --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink
```

成功时通常会看到：

```text
Programming Finished
Verified OK
Resetting Target
```

`flash` 会真实改写目标芯片 Flash。Debug-only 模式下，VS Code 调试配置默认 `loadFiles: []`，不会由调试动作下载固件。

## 5. VS Code 使用方式

不要只打开 `.keilbridge/generated`。应该打开 KeilBridge 生成的 `.code-workspace`：

```text
<keil-project-root>\.keilbridge\KeilBridge_<target>.code-workspace
<keil-project-root>\.keilbridge\KeilBridge_<target>_armclang.code-workspace
<keil-project-root>\.keilbridge\KeilBridge_<target>_debug.code-workspace
```

原因：

- 工作区同时包含原始源码和生成文件。
- 断点应该下在原始源码里。
- launch/tasks 使用当前电脑探测到的工具路径。
- Debug-only 可包含 `sourceFileMap`，处理 Keil AXF 里的旧源码路径。

## 6. 三种方式的简要原理

### 6.1 GCC/CMake

KeilBridge 解析 `.uvprojx`，抽取源文件、include、define、芯片内存和启动信息，生成外部 CMake 工程。构建由 CMake/Ninja/Arm GCC 完成，调试由 OpenOCD/GDB/Cortex-Debug 完成。

适合长期开放化、脚本化、CI 化。

### 6.2 ArmClang

KeilBridge 生成使用 ArmClang/ArmLink 的外部工作区，尽量保留 Keil/Arm 工具链语义。它更适合历史 Keil 工程、scatter/ArmLink 语义较重的工程。

当前定位是兼容迁移路线，仍需要逐项目实机验证。

### 6.3 Debug-only

KeilBridge 不构建用户固件，只使用已有 Keil `.axf/.elf` 作为符号文件，生成 VS Code/OpenOCD/GDB 调试入口。固件由 Keil 或用户原有方式编译和烧录。

适合短期过渡、现场调试、AI 调试信息采集和无法马上迁移的工程。

## 7. 已验证示例：MCU_userapp_motor

目标工程：

```text
D:\GD32\GDproject\MCU_userapp_motor
```

Keil 工程：

```text
D:\GD32\GDproject\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx
```

Keil 产物：

```text
D:\GD32\GDproject\MCU_userapp_motor\MDK-ARM\HS_STEP_42C\HS_STEP_42C.axf
```

实测命令：

```powershell
cd D:\GD32\GDproject\KeilTool

python -m keiltool.cli inspect "D:\GD32\GDproject\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C -v

python -m keiltool.cli configure `
  --project "D:\GD32\GDproject\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" `
  --target HS_STEP_42C `
  --backend debug-only `
  --probe stlink `
  --elf "D:\GD32\GDproject\MCU_userapp_motor\MDK-ARM\HS_STEP_42C\HS_STEP_42C.axf"

python -m keiltool.cli doctor flash `
  --project "D:\GD32\GDproject\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" `
  --target HS_STEP_42C `
  --probe stlink `
  --run
```

已验证结果：

```text
OpenOCD 可连接 STM32G431CBUx
reset/halt 后 PC/MSP 有效
arm-none-eabi-gdb 可读取 Keil AXF 符号
GDB 可对 main 设置硬件断点
VS Code 可正常打断点
```

打开：

```text
D:\GD32\GDproject\MCU_userapp_motor\.keilbridge\KeilBridge_HS_STEP_42C_debug.code-workspace
```

## 8. 路径和生成目录

每个目标工程独立生成：

```text
<keil-project-root>\.keilbridge\generated\
<keil-project-root>\.keilbridge\build\
<keil-project-root>\.keilbridge\logs\
<keil-project-root>\.keilbridge\KeilBridge_<target>*.code-workspace
```

换电脑、换工程目录、换工具链路径后，建议重新运行 `configure`。

## 9. 常见问题

常见问题已经移到单独文档：

```text
docs\03_KeilBridge_FAQ.md
```
