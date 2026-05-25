# KeilBridge 用户使用手册

## 1. KeilBridge 是什么

KeilBridge 用来给现有 Keil MDK 工程生成一套外部 CMake/GCC/OpenOCD/VS Code 构建与调试入口。

核心边界：

- 不修改用户源码。
- 不修改 `.uvprojx`、`.uvoptx`、`.ioc`。
- 不移动用户工程目录。
- 不要求用户手工维护 CMake 源文件列表。
- 默认只在目标 Keil 工程根目录新增 `.keilbridge/`。

当前主入口命令是：

```powershell
python -m keiltool.cli <command> ...
```

执行命令前，先进入 KeilBridge 工具目录：

```powershell
cd D:\GD32\GDproject\KeilTool
```

## 2. 一条完整使用流程

下面是正常用户从 Keil 工程到 CMake 编译、烧录、VS Code 调试的完整流程。

### 2.1 查看工程信息

```powershell
python -m keiltool.cli inspect "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" --target App -v
```

作用：

- 查看 Keil target 是否识别正确。
- 查看芯片型号、内核、FPU、内存、OpenOCD target。
- 查看源文件、include、define、startup、scatter。
- 查看 CubeMX、RTOS、CMSIS-DSP、ARMCC `.lib` 等风险提示。

如果不确定 target 名，可以先不加 `--target`，或看报错里的 `Available targets`。

### 2.2 生成外部工作区

```powershell
python -m keiltool.cli configure --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" --target App --probe cmsis-dap
```

常见探针参数：

- `--probe cmsis-dap`：DAPLink、CMSIS-DAP。
- `--probe daplink`：DAPLink，当前等价于 CMSIS-DAP。
- `--probe stlink`：ST-Link。

生成位置：

```text
<keil-project-root>\.keilbridge\
  generated\
  build\
  logs\
```

### 2.3 编译

```powershell
python -m keiltool.cli build --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" --target App
```

成功后产物在：

```text
<keil-project-root>\.keilbridge\build\gcc-debug\App.elf
<keil-project-root>\.keilbridge\build\gcc-debug\App.hex
<keil-project-root>\.keilbridge\build\gcc-debug\App.bin
<keil-project-root>\.keilbridge\build\gcc-debug\App.map
```

第二次编译会走 Ninja 增量构建。没有文件变化时通常会显示：

```text
ninja: no work to do.
```

### 2.4 先诊断烧录链路

```powershell
python -m keiltool.cli doctor flash --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" --target App --probe cmsis-dap --run
```

作用：

- 检查 OpenOCD 是否能启动。
- 检查 DAPLink/ST-Link 是否能连接。
- 检查复位后 PC/MSP 是否看起来有效。
- 生成诊断报告。

报告位置：

```text
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_report.md
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_result.json
```

注意：`doctor flash --run` 只诊断，不下载固件。

### 2.5 真正烧录

```powershell
python -m keiltool.cli flash --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" --target App --probe cmsis-dap
```

成功输出应包含：

```text
** Programming Finished **
** Verify Started **
** Verified OK **
** Resetting Target **
```

`flash` 会真实覆盖芯片 Flash。它默认烧录：

```text
<keil-project-root>\.keilbridge\build\gcc-debug\App.elf
```

如果要指定 ELF：

```powershell
python -m keiltool.cli flash --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" --target App --probe cmsis-dap --elf "D:\firmware\App.elf"
```

### 2.6 在 VS Code 里调试

不要打开：

```text
<keil-project-root>\.keilbridge\generated
```

应该打开 KeilBridge 生成的多根工作区：

```text
<keil-project-root>\.keilbridge\KeilBridge_<target>.code-workspace
```

原因：

- 工作区会同时包含原始源码和 generated 目录。
- 左侧能看到完整源码树。
- 断点应下在原始源码里，不是在 generated 副本里。
- launch/tasks 使用绝对路径，避免 VS Code 多根工作区路径解析错乱。

VS Code 需要插件：

- C/C++。
- CMake Tools。
- Cortex-Debug。

调试时选择类似下面的配置：

```text
KeilBridge OpenOCD (cmsis-dap)
```

## 3. `--target` 是什么

Keil 一个 `.uvprojx` 里可以有多个 Target，例如：

```text
Debug
Release
Template
HS_STEP_42C
Sentry_gimbal
```

`--target` 用来指定你要转换哪一个 Keil Target：

```powershell
python -m keiltool.cli inspect "xxx.uvprojx" --target Template -v
```

如果 target 写错，工具会提示：

```text
Target not found: xxx. Available targets: Template
```

这时把 `--target` 改成 `Available targets` 里列出的名字即可。

## 4. 真实示例

### 4.1 STM32G431 42Step 工程

```powershell
cd D:\GD32\GDproject\KeilTool

python -m keiltool.cli inspect "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C -v

python -m keiltool.cli configure --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C --probe stlink

python -m keiltool.cli build --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C

python -m keiltool.cli doctor flash --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C --probe stlink --run

python -m keiltool.cli flash --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C --probe stlink
```

### 4.2 STM32F405 Sentry 24 工程

```powershell
cd D:\GD32\GDproject\KeilTool

python -m keiltool.cli inspect "C:\Users\86199\Desktop\sentry\sentry\24sentry\24-Sentry-Gimbal\MDK-ARM\Template.uvprojx" --target Template -v

python -m keiltool.cli configure --project "C:\Users\86199\Desktop\sentry\sentry\24sentry\24-Sentry-Gimbal\MDK-ARM\Template.uvprojx" --target Template --probe cmsis-dap

python -m keiltool.cli build --project "C:\Users\86199\Desktop\sentry\sentry\24sentry\24-Sentry-Gimbal\MDK-ARM\Template.uvprojx" --target Template

python -m keiltool.cli doctor flash --project "C:\Users\86199\Desktop\sentry\sentry\24sentry\24-Sentry-Gimbal\MDK-ARM\Template.uvprojx" --target Template --probe cmsis-dap --run

python -m keiltool.cli flash --project "C:\Users\86199\Desktop\sentry\sentry\24sentry\24-Sentry-Gimbal\MDK-ARM\Template.uvprojx" --target Template --probe cmsis-dap
```

打开 VS Code 工作区：

```text
C:\Users\86199\Desktop\sentry\sentry\24sentry\24-Sentry-Gimbal\.keilbridge\KeilBridge_Template.code-workspace
```

### 4.3 STM32F405 Sentry 25 工程

```powershell
cd D:\GD32\GDproject\KeilTool

python -m keiltool.cli inspect "C:\Users\86199\Desktop\sentry\sentry\25_Sentry\25Sentry\25Sentry_gimbal\MDK-ARM\Sentry_gimbal.uvprojx" --target Sentry_gimbal -v

python -m keiltool.cli configure --project "C:\Users\86199\Desktop\sentry\sentry\25_Sentry\25Sentry\25Sentry_gimbal\MDK-ARM\Sentry_gimbal.uvprojx" --target Sentry_gimbal --probe cmsis-dap

python -m keiltool.cli build --project "C:\Users\86199\Desktop\sentry\sentry\25_Sentry\25Sentry\25Sentry_gimbal\MDK-ARM\Sentry_gimbal.uvprojx" --target Sentry_gimbal

python -m keiltool.cli doctor flash --project "C:\Users\86199\Desktop\sentry\sentry\25_Sentry\25Sentry\25Sentry_gimbal\MDK-ARM\Sentry_gimbal.uvprojx" --target Sentry_gimbal --probe cmsis-dap --run

python -m keiltool.cli flash --project "C:\Users\86199\Desktop\sentry\sentry\25_Sentry\25Sentry\25Sentry_gimbal\MDK-ARM\Sentry_gimbal.uvprojx" --target Sentry_gimbal --probe cmsis-dap
```

打开 VS Code 工作区：

```text
C:\Users\86199\Desktop\sentry\sentry\25_Sentry\25Sentry\25Sentry_gimbal\.keilbridge\KeilBridge_Sentry_gimbal.code-workspace
```

## 5. 多个工程会不会互相覆盖

不会。

KeilBridge 的生成目录放在各自 Keil 工程根目录：

```text
D:\Projects\A\.keilbridge\
D:\Projects\B\.keilbridge\
```

即使两个工程 target 都叫 `App`，产物也分别在各自工程下：

```text
D:\Projects\A\.keilbridge\build\gcc-debug\App.elf
D:\Projects\B\.keilbridge\build\gcc-debug\App.elf
```

KeilBridge 工具目录本身不保存这些工程产物。

## 6. 换电脑怎么用

建议迁移：

```text
KeilBridge 工具目录
目标 Keil 工程目录
```

不建议迁移：

```text
<keil-project-root>\.keilbridge\generated
<keil-project-root>\.keilbridge\build
__pycache__
```

原因：

- `generated` 里包含当前电脑的绝对路径。
- `build` 里包含 CMake/Ninja 缓存。
- 换电脑后用户名、工具链路径、OpenOCD 路径可能不同。

新电脑推荐步骤：

1. 安装 Python 3.10+。
2. 安装 Arm GNU Toolchain `arm-none-eabi`。
3. 安装 CMake 和 Ninja，或使用 Visual Studio 2022 自带的 CMake/Ninja。
4. 安装 OpenOCD，推荐 xPack OpenOCD、STM32CubeCLT OpenOCD 或系统独立 OpenOCD。
5. 进入 KeilBridge 工具目录。
6. 重新执行 `configure`。
7. 重新执行 `build`。
8. 重新打开 `.keilbridge\KeilBridge_<target>.code-workspace`。

如果工具链不在常见路径，可以显式指定：

```powershell
python -m keiltool.cli build `
  --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" `
  --target App `
  --cmake "C:\Program Files\CMake\bin\cmake.exe" `
  --ninja "C:\ninja\ninja.exe" `
  --arm-gcc-root "C:\Toolchains\Arm GNU Toolchain arm-none-eabi\14.2 rel1"
```

如果 OpenOCD 不在常见路径，可以显式指定：

```powershell
python -m keiltool.cli doctor flash `
  --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" `
  --target App `
  --probe cmsis-dap `
  --openocd "C:\OpenOCD\bin\openocd.exe" `
  --run
```

烧录时同样可以指定：

```powershell
python -m keiltool.cli flash `
  --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" `
  --target App `
  --probe cmsis-dap `
  --openocd "C:\OpenOCD\bin\openocd.exe"
```

## 7. 什么时候需要重新 configure

只改 `.c/.h`：

```powershell
python -m keiltool.cli build --project "xxx.uvprojx" --target App
```

需要重新 `configure` 的情况：

- Keil 里新增或删除源文件。
- Keil include path 变化。
- Keil define 变化。
- 切换 Keil Target。
- 切换探针，例如 `stlink` 改成 `cmsis-dap`。
- 换电脑。
- 删除了 `.keilbridge/generated`。

推荐流程：

```powershell
python -m keiltool.cli configure --project "xxx.uvprojx" --target App --probe cmsis-dap
python -m keiltool.cli build --project "xxx.uvprojx" --target App
```

## 8. 常见问题

### 8.1 `doctor flash --run` 和 `flash` 有什么区别

`doctor flash --run`：

- 只诊断连接、OpenOCD、探针、复位向量。
- 不下载固件。
- 会生成报告。

`flash`：

- 真正执行 OpenOCD `program <elf> verify reset exit`。
- 会覆盖芯片 Flash。
- 成功标准是 `Programming Finished` 和 `Verified OK`。

### 8.2 VS Code 里看不到完整源码怎么办

不要打开：

```text
<keil-project-root>\.keilbridge\generated
```

打开：

```text
<keil-project-root>\.keilbridge\KeilBridge_<target>.code-workspace
```

然后在 `Original Source` 里的原始源码文件上下断点。

### 8.3 OpenOCD 显示 GDB Server Quit Unexpectedly 怎么办

先执行：

```powershell
python -m keiltool.cli doctor flash --project "xxx.uvprojx" --target App --probe cmsis-dap --run
```

再查看报告：

```text
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_report.md
```

常见原因：

- OpenOCD 版本不适合当前芯片，例如用 ESP-IDF OpenOCD 调 STM32/GD32。
- DAPLink/CMSIS-DAP 被串口工具、旧 OpenOCD、旧 GDB 占用。
- 目标芯片 OpenOCD cfg 不匹配。
- 板子没有供电或 SWD 接线异常。
- 复位线配置不匹配。

### 8.4 `preLaunchTask "CMake: build" 已终止` 怎么办

如果 VS Code 调试前弹窗：

```text
preLaunchTask "CMake: build" 已终止，退出代码为 1
cmake: 无法将 "cmake" 项识别为 cmdlet、函数、脚本文件或可运行程序的名称
```

原因通常是旧版 `.keilbridge/generated/.vscode/tasks.json` 依赖 PATH 里的 `cmake`，但 VS Code task 环境找不到 `cmake.exe`。

解决方法：

1. 回到 KeilBridge 工具目录。
2. 重新执行 `configure`。
3. 重新打开 `.keilbridge\KeilBridge_<target>.code-workspace`。

示例：

```powershell
cd D:\GD32\GDproject\KeilTool
python -m keiltool.cli configure --project "C:\Path\To\YourProject\MDK-ARM\App.uvprojx" --target App --probe cmsis-dap
```

新版生成结果里，调试配置应使用：

```text
preLaunchTask: KeilBridge: build
```

构建任务应使用当前电脑上已发现的绝对 `cmake.exe` 路径，而不是 `cmake --preset ...`。

### 8.5 `CMSIS-DAP command mismatch` 怎么办

如果烧录时出现：

```text
Error: CMSIS-DAP command mismatch. Sent 0x11 received 0x5
Error: CMSIS-DAP command CMD_DAP_SWJ_CLOCK failed.
Error: Failed to write memory at 0x20001a58
Error: error writing to flash at address 0x08000000 at offset 0x00000000
** Programming Failed **
```

含义：

- OpenOCD 已经识别到芯片。
- 烧录已经进入 `program` 阶段。
- 失败发生在 CMSIS-DAP/DAPLink 与 OpenOCD 的通信层。
- 这通常不是 CMake、链接脚本或 ELF 本身的问题。

建议按顺序处理：

1. 结束所有 `openocd.exe`、`arm-none-eabi-gdb.exe`、VS Code gdb-server 终端。
2. 关闭串口监视器、DAPLink 文件拖拽窗口和其他可能占用调试器的软件。
3. 重新插拔 DAPLink。
4. 重新执行 `doctor flash --run`。
5. 再执行 `flash`。
6. 如果仍然复现，优先换用 xPack OpenOCD、STM32CubeCLT OpenOCD 或系统独立 OpenOCD，不建议长期用 ESP-IDF 打包的 `openocd-esp32` 调 STM32/GD32。
7. 如果通信层稳定后仍写入失败，再检查读保护、供电、SWD 接线、复位线和 OpenOCD target cfg。

### 8.6 ARMCC `.lib` 为什么会提示风险

Keil 工程里常见：

```text
arm_cortexM4lf_math.lib
```

这类 `.lib` 通常是 ARMCC/Keil 格式，GCC 不能保证直接链接。KeilBridge 当前策略：

- `inspect` 会诊断为 `armcc_library`。
- GCC 构建不会盲目链接 ARMCC `.lib`。
- 对少数 CMSIS-DSP 符号有兼容兜底。
- 如果工程用到更多 DSP API，可能仍然链接失败。
- 完整方案需要 GCC 可用的 CMSIS-DSP 源码或 `.a`。

### 8.7 用户源码报错会不会被自动修

不会。

如果用户源码本身有语法错误，`build` 应该失败并显示编译器报错。KeilBridge 不会默认修改原始源码。少数机械兼容处理只会生成 overlay 副本，原工程不动。

### 8.8 一进调试就卡在 HardFault 怎么办

先不要只看 `HardFault_Handler` 本身。HardFault 是结果，不是原因。KeilBridge 需要采集：

```text
PC / LR / MSP / PSP / xPSR
CFSR / HFSR / MMFAR / BFAR
异常栈帧里的原始 PC/LR
```

24-Sentry 曾经出现过一次典型问题：全局 C++ 对象 `attitudeAlgorithm` 有虚函数，但 GCC 链接脚本没有保留 `.init_array`，导致 C++ 全局构造函数没有执行，对象虚表指针为 0，FreeRTOS 任务运行后虚函数调用跳到非法地址并 HardFault。

这个问题已经在 KeilBridge 里修复：

- startup 调用 `__libc_init_array()`。
- linker script 保留 `.preinit_array/.init_array/.fini_array/.ctors/.dtors`。
- 重新 `configure/build/flash` 后生效。

如果你遇到类似问题，先重新生成并烧录：

```powershell
python -m keiltool.cli configure --project "xxx.uvprojx" --target App --probe cmsis-dap
python -m keiltool.cli build --project "xxx.uvprojx" --target App
python -m keiltool.cli flash --project "xxx.uvprojx" --target App --probe cmsis-dap
```

如果仍然 HardFault，再采集 Fault 现场，而不是直接改用户源码。

### 8.9 CubeMX 工程支持吗

当前策略是识别并复用：

- 识别 `.ioc`、STM32 HAL、Core、Drivers、Middlewares。
- 复用 Keil target 中已有源文件、include、define。
- 不调用 CubeMX。
- 不修改 `.ioc`。
- 不改 `USER CODE`。

### 8.10 RTOS 工程支持吗

当前策略是识别、诊断、对已验证组合做映射：

- 已能识别 FreeRTOS、RT-Thread、ThreadX、uCOS 等常见形态。
- FreeRTOS ARMCC/RVDS port 到 GCC port 的映射只对已验证组合启用。
- 不承诺自动解决所有 heap、BSP、中间件组合问题。

### 8.11 GD32 支持吗

已经有初步支持：

- 能识别 `GD32...` 芯片名。
- 已加入少量 GD32F1/F3/F4/E2/L2 seed 条目。
- GD32F303CB 已用 DAPLink/CMSIS-DAP + OpenOCD 完成编译、下载、verify、GDB 命中 `main` 的实板验证。
- 其他 GD32 型号需要继续用真实板卡验证后沉淀到设备数据库。

## 9. 快速命令模板

把下面的路径和 target 改成自己的即可：

```powershell
$project = "C:\Path\To\YourProject\MDK-ARM\App.uvprojx"
$target = "App"
$probe = "cmsis-dap"

cd D:\GD32\GDproject\KeilTool

python -m keiltool.cli inspect $project --target $target -v
python -m keiltool.cli configure --project $project --target $target --probe $probe
python -m keiltool.cli build --project $project --target $target
python -m keiltool.cli doctor flash --project $project --target $target --probe $probe --run
python -m keiltool.cli flash --project $project --target $target --probe $probe
```
