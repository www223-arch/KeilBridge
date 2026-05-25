# KeilBridge 用户使用手册

## 1. 工具用途

KeilBridge 用来给现有 Keil MDK 工程生成一套 GCC/CMake/OpenOCD/VS Code 外部构建与调试入口。

核心边界：

- 不修改用户源码。
- 不修改 Keil 工程文件。
- 不移动用户工程目录。
- 不替用户修代码。
- 默认只在目标 Keil 工程根目录新增 `.keilbridge/` 工作目录。

## 2. 生成目录放在哪里？

默认放在**目标 Keil 工程根目录**，不是放在 KeilBridge 工具目录。

例如目标工程是：

```text
C:\Users\86199\Desktop\42Step\MCU_userapp_motor
  Core/
  Drivers/
  User/
  MDK-ARM/HS_STEP_42C.uvprojx
```

执行 `configure` 后会生成：

```text
C:\Users\86199\Desktop\42Step\MCU_userapp_motor\.keilbridge\
  generated/
    CMakeLists.txt
    CMakePresets.json
    cmake/
    linker/
    startup/
    support/
    .vscode/
  build/
    gcc-debug/
```

这样做的好处：

- 每个 Keil 工程有自己的 `.keilbridge/`。
- 多个工程来回编译不会互相覆盖。
- CMake/Ninja 缓存天然按工程隔离。
- 删除 `.keilbridge/` 后可以重新生成。

## 3. 首次使用

进入 KeilBridge 工具目录：

```powershell
cd D:\GD32\GDproject\KeilTool
```

检查 Keil 工程：

```powershell
python -m keiltool.cli inspect "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C -v
```

生成该工程自己的 `.keilbridge/`：

```powershell
python -m keiltool.cli configure --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C --probe stlink
```

编译：

```powershell
python -m keiltool.cli build --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C
```

产物位置：

```text
C:\Users\86199\Desktop\42Step\MCU_userapp_motor\.keilbridge\build\gcc-debug\HS_STEP_42C.elf
C:\Users\86199\Desktop\42Step\MCU_userapp_motor\.keilbridge\build\gcc-debug\HS_STEP_42C.hex
C:\Users\86199\Desktop\42Step\MCU_userapp_motor\.keilbridge\build\gcc-debug\HS_STEP_42C.bin
C:\Users\86199\Desktop\42Step\MCU_userapp_motor\.keilbridge\build\gcc-debug\HS_STEP_42C.map
```

## 4. 日常增量编译

如果只是改 `.c/.h`，直接运行：

```powershell
python -m keiltool.cli build --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C
```

Ninja 会自动增量构建：

- 没有文件变化：`ninja: no work to do.`
- 只改一个 `.c`：只重编该文件并重新链接。
- 改公共 `.h`：依赖它的源文件会重编。

如果 Keil 工程结构变了，例如新增源文件、include 路径变化、宏定义变化，先重新执行：

```powershell
python -m keiltool.cli configure --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C --probe stlink
```

再执行 `build`。

## 5. 多个工程如何使用？

每个工程都用自己的 `.uvprojx` 执行 `configure`。

工程 A：

```powershell
python -m keiltool.cli configure --project "D:\Projects\A\MDK-ARM\App.uvprojx" --target App
python -m keiltool.cli build --project "D:\Projects\A\MDK-ARM\App.uvprojx" --target App
```

工程 B：

```powershell
python -m keiltool.cli configure --project "D:\Projects\B\MDK-ARM\App.uvprojx" --target App
python -m keiltool.cli build --project "D:\Projects\B\MDK-ARM\App.uvprojx" --target App
```

生成目录分别是：

```text
D:\Projects\A\.keilbridge\
D:\Projects\B\.keilbridge\
```

即使两个工程 target 都叫 `App`，也不会互相覆盖。

## 6. OpenOCD 调试

生成 OpenOCD 命令：

```powershell
python -m keiltool.cli openocd --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C --probe stlink
```

示例输出：

```text
openocd -f interface/stlink.cfg -f target/stm32g4x.cfg
```

如果 OpenOCD 不在 PATH：

```powershell
python -m keiltool.cli openocd --project "C:\Users\86199\Desktop\42Step\MCU_userapp_motor\MDK-ARM\HS_STEP_42C.uvprojx" --target HS_STEP_42C --probe stlink --openocd "C:\OpenOCD\bin\openocd.exe"
```

VS Code 调试配置在：

```text
<keil-project-root>\.keilbridge\generated\.vscode\launch.json
<keil-project-root>\.keilbridge\generated\.vscode\tasks.json
```

用 VS Code 打开：

```text
<keil-project-root>\.keilbridge\generated
```

即可看到 Cortex-Debug 配置。

## 7. 换电脑怎么用？

建议迁移：

```text
KeilBridge 工具目录
目标 Keil 工程目录
```

不建议迁移：

```text
目标 Keil 工程目录\.keilbridge\
__pycache__/
```

原因：

- `.keilbridge/generated` 里包含本机绝对路径。
- `.keilbridge/build` 里包含 CMake/Ninja 缓存。
- 换电脑后用户名、工具链路径、OpenOCD 路径可能不同。

新电脑推荐步骤：

1. 安装 Python 3.10+。
2. 安装 Arm GNU Toolchain arm-none-eabi。
3. 安装 CMake 和 Ninja，或安装 Visual Studio 2022 自带 CMake/Ninja。
4. 安装 OpenOCD，或准备 STM32CubeIDE/xPack OpenOCD 路径。
5. 进入 KeilBridge 工具目录。
6. 重新执行 `configure`。
7. 重新执行 `build`。

如果工具链不在常见路径，可以显式指定：

```powershell
python -m keiltool.cli build `
  --project "新电脑上的Keil工程路径\MDK-ARM\HS_STEP_42C.uvprojx" `
  --target HS_STEP_42C `
  --cmake "C:\Program Files\CMake\bin\cmake.exe" `
  --ninja "C:\ninja\ninja.exe" `
  --arm-gcc-root "C:\Toolchains\Arm GNU Toolchain arm-none-eabi\14.2 rel1"
```

如果 OpenOCD 不在 PATH：

```powershell
python -m keiltool.cli openocd `
  --project "新电脑上的Keil工程路径\MDK-ARM\HS_STEP_42C.uvprojx" `
  --target HS_STEP_42C `
  --probe stlink `
  --openocd "C:\OpenOCD\bin\openocd.exe"
```

## 8. 是否仍然 0 侵入？

这里的“0 侵入”指：

- 不改用户源码。
- 不改 Keil 工程文件。
- 不改 CubeMX `.ioc`。
- 不移动目录结构。
- 不要求用户维护 CMake 文件列表。

新增 `.keilbridge/` 属于工具生成缓存目录，类似 Keil 的输出目录或 CMake 的 build 目录。

如果用户完全不想在原工程目录生成任何文件，可以后续使用 `--workspace-root` 指定外部目录。

## 9. 常见问题

### 9.1 `.keilbridge/` 可以删除吗？

可以。删除后重新执行：

```powershell
python -m keiltool.cli configure --project "xxx.uvprojx" --target TargetName
python -m keiltool.cli build --project "xxx.uvprojx" --target TargetName
```

### 9.2 用户源码有错误怎么办？

KeilBridge 不会自动修复用户源码。

如果用户代码本身存在语法错误，`build` 应该正常失败，并显示 GCC 报错。请在原 Keil 工程中修复源码后再重新构建。

### 9.3 第二次编译为什么很快？

KeilBridge 使用 CMake + Ninja。第一次会全量编译；第二次如果文件没变，Ninja 会显示：

```text
ninja: no work to do.
```

这说明增量构建生效了。

## 10. CubeMX、RTOS、GD32 怎么理解？

### 10.1 CubeMX 工程

KeilBridge 当前对 CubeMX 的策略是“识别并复用”：

- 识别 `.ioc`、STM32 HAL、Core/Drivers/Middlewares 等常见工程形态。
- 复用 Keil target 中已经选中的源文件、include、define。
- 不调用 CubeMX。
- 不修改 `.ioc`。
- 不改 `USER CODE` 区域。

如果 CubeMX 工程里还有 Keil 没有加入 target 的文件，KeilBridge 也不会凭空猜测加入；这类情况后续通过诊断报告和 override 机制处理。

### 10.2 RTOS 工程

KeilBridge 当前对 RTOS 的策略是“识别、提示风险、对已验证组合做外部映射”：

- 已开始识别 FreeRTOS、RT-Thread、ThreadX、uCOS 等常见路径。
- 生成报告会提示 RTOS port 可能存在 ARMCC/GCC 差异。
- 对已验证的 FreeRTOS `portable/RVDS/ARM_CM4F` 工程，外部 GCC 构建会映射到 `portable/GCC/ARM_CM4F`，原工程不动。
- 当前不会自动修复 heap 文件重复、BSP 移植层差异等问题。

也就是说，加 RTOS 的工程可以先跑 `inspect` 和 `configure`。如果属于已验证 adapter，KeilBridge 会在生成层处理；如果没有 adapter，就让 GCC 报出真实错误，不会偷偷修改你的源码。

### 10.3 GD32 工程

KeilBridge 已加入 GD32 的初步支持：

- 能识别 `GD32...` 芯片名。
- 已有少量 GD32F1/F3/F4/E2/L2 seed 设备条目。
- 能识别 GD32 标准库常见路径。
- GD32F303CB 已用 DAPLink/CMSIS-DAP + OpenOCD `stm32f3x.cfg` 完成编译、下载、verify、GDB 命中 `main` 的实板验证。
- 其他 GD32 型号仍会在报告里标记“需要真实板子验证”，确认后再沉淀到设备数据库。

GD32 推荐验证流程：

```powershell
python -m keiltool.cli inspect "D:\path\to\your_gd_project.uvprojx" -v
python -m keiltool.cli configure --project "D:\path\to\your_gd_project.uvprojx" --target TargetName --probe stlink
python -m keiltool.cli build --project "D:\path\to\your_gd_project.uvprojx" --target TargetName
python -m keiltool.cli openocd --project "D:\path\to\your_gd_project.uvprojx" --target TargetName --probe stlink
```

生成报告位置：

```text
<keil-project-root>\.keilbridge\generated\reports\project_ir.json
<keil-project-root>\.keilbridge\generated\reports\conversion_report.md
```

`project_ir.json` 给工具和后续适配用，`conversion_report.md` 给人看，里面会列出芯片、工程形态、RTOS、中间件、OpenOCD target 和风险。

## 11. CMSIS-DSP / ARMCC `.lib` 风险

很多 Keil 工程会引用类似下面的库：

```text
arm_cortexM4lf_math.lib
```

这类 `.lib` 通常是 ARMCC/Keil 格式，GCC 不能直接链接。KeilBridge 的处理边界如下：

- `inspect` 会把它报告为 `armcc_library`。
- 生成 GCC 工程时不会直接链接这个 ARMCC `.lib`。
- 当前只提供最小 `arm_math_compat.c` 兜底，覆盖少量已验证符号，例如 `arm_sin_f32`、`arm_cos_f32`。
- 如果工程调用更多 CMSIS-DSP API，可能在链接阶段出现 `undefined reference`。
- 完整支持需要后续接入 GCC 可用的 CMSIS-DSP 源码或 `.a` 库，或者由用户配置替代库路径。

因此，某个工程能编过，只能说明“当前工程实际用到的 DSP 符号已覆盖或未触发”，不能说明 ARMCC DSP 库已经被完整替换。
