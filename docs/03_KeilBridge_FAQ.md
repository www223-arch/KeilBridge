# KeilBridge FAQ

这里放使用过程中的常见问题。主流程请先看 `01_KeilBridge_用户使用手册.md`。

## 1. `doctor flash --run` 和 `flash` 有什么区别？

`doctor flash --run` 只做连接诊断：

- 启动 OpenOCD。
- 连接探针和目标芯片。
- reset/halt。
- 读取启动向量或 PC/MSP。
- 生成诊断报告。

它不下载固件。

`flash` 会真实烧录：

```powershell
python -m keiltool.cli flash --project "xxx.uvprojx" --target App --probe stlink
```

它会执行 OpenOCD `program <elf> verify reset exit`，会改写目标芯片 Flash。

## 2. Debug-only 会帮我编译或下载固件吗？

不会。

Debug-only 的定位是“调试已有固件”：

- `.axf/.elf` 通常由 Keil IDE、Keil 命令行或项目原有构建脚本生成。
- 固件下载通常也由 Keil 或项目原有下载流程完成。
- KeilBridge 生成的 Debug-only VS Code 配置默认 `loadFiles: []`，不会在启动调试时下载固件。

所以 Debug-only 的推荐顺序是：

1. 用 Keil、KeilBridge 的 `keil build/rebuild`，或原有脚本编译，生成带符号的 `.axf/.elf`。
2. 用 Keil、KeilBridge 的 `keil download`，或原有下载流程把对应固件下载到目标板。
3. 运行 `configure --backend debug-only --elf ...`。
4. 打开生成的 `KeilBridge_<target>_debug.code-workspace`，选择 Attach 或 Reset/Halt 调试。

如果 `.axf/.elf` 更新了但板子里的固件没更新，调试符号和实际运行程序可能不一致，断点、变量、调用栈都会变得不可信。

## 3. KeilBridge 怎么调用 Keil 命令行？

KeilBridge 提供三个封装命令：

```powershell
python -m keiltool.cli keil build --project "xxx.uvprojx" --target App
python -m keiltool.cli keil rebuild --project "xxx.uvprojx" --target App
python -m keiltool.cli keil download --project "xxx.uvprojx" --target App
```

对应 Keil µVision CLI：

- `build`：`UV4.exe -b ...`
- `rebuild`：`UV4.exe -r ...`
- `download`：`UV4.exe -f ...`

如果 `UV4.exe` 不在 PATH 或常见安装目录，可以传：

```powershell
python -m keiltool.cli keil build --project "xxx.uvprojx" --target App --uvision "C:\Keil_v5\UV4\UV4.exe"
```

如果当前工程有 Keil 生成的 `<target>.BAT`，`keil build/rebuild` 在找不到 `UV4.exe` 时会自动运行 BAT 副本。这个副本位于 `.keilbridge/generated/keil-batch/`，原始 BAT 不会被修改。`keil download` 仍需要 `UV4.exe`，因为下载动作依赖 Keil target 的 Flash Download 配置。

日志在：

```text
<keil-project-root>\.keilbridge\logs\keil_<action>_<target>_<time>.log
```

## 4. 报告在哪里？

后端推荐报告：

```text
<keil-project-root>\.keilbridge\generated\reports\backend_recommendation.md
<keil-project-root>\.keilbridge\generated\reports\backend_recommendation.json
```

Flash Doctor 报告：

```text
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_report.md
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_result.json
<keil-project-root>\.keilbridge\logs\
```

ELF Doctor 报告：

```text
<keil-project-root>\.keilbridge\generated\reports\elf_doctor_report.md
<keil-project-root>\.keilbridge\generated\reports\elf_doctor_result.json
```

Debug-only 工作区报告：

```text
<keil-project-root>\.keilbridge\generated\reports\debug_only_workspace.md
<keil-project-root>\.keilbridge\generated\reports\debug_only_workspace.json
```

## 5. VS Code 里看不到完整源码怎么办？

不要打开：

```text
<keil-project-root>\.keilbridge\generated
```

应该打开：

```text
<keil-project-root>\.keilbridge\KeilBridge_<target>.code-workspace
```

或对应的：

```text
KeilBridge_<target>_debug.code-workspace
KeilBridge_<target>_armclang.code-workspace
```

这些 workspace 会同时包含原始源码和生成目录。

## 6. Debug-only 断点灰色、跳到反汇编怎么办？

Keil `.axf` 里保存的是编译时源码路径。如果当前工程路径和编译时路径不同，需要 `sourceFileMap`。

例子：

```json
"sourceFileMap": {
  "C:/Users/86199/Desktop/42Step/MCU_userapp_motor": "D:/GD32/GDproject/MCU_userapp_motor"
}
```

换电脑或换目录后，重新运行 `configure --backend debug-only`，必要时手动检查生成的 `.code-workspace`。

## 7. `GDB Server Quit Unexpectedly` 怎么办？

先跑：

```powershell
python -m keiltool.cli doctor flash --project "xxx.uvprojx" --target App --probe stlink --run
```

再看：

```text
<keil-project-root>\.keilbridge\generated\reports\flash_doctor_report.md
```

常见原因：

- OpenOCD 版本不适合当前芯片。
- 探针被旧的 OpenOCD、GDB、串口工具或 IDE 占用。
- OpenOCD interface/target cfg 不匹配。
- 板子没供电、SWD 接线异常、复位线异常。
- 芯片读保护或处于异常低功耗/锁死状态。

## 8. `CMSIS-DAP command mismatch` 怎么办？

常见输出：

```text
Error: CMSIS-DAP command mismatch
Error: CMSIS-DAP command CMD_DAP_SWJ_CLOCK failed
Error: Failed to write memory
```

这通常是 CMSIS-DAP/DAPLink 与 OpenOCD 的通信层问题，不一定是 ELF 或 CMake 问题。

处理顺序：

1. 关闭 VS Code 调试会话。
2. 结束旧的 `openocd.exe` 和 `arm-none-eabi-gdb.exe`。
3. 关闭串口监视器和可能占用探针的软件。
4. 重新插拔探针。
5. 重新运行 `doctor flash --run`。
6. 仍然失败时，换用 xPack OpenOCD 或 STM32CubeCLT OpenOCD。

## 9. `preLaunchTask "CMake: build" 已终止` 怎么办？

这通常是旧生成文件依赖 PATH 中的 `cmake`，但 VS Code task 环境找不到。

处理：

```powershell
cd D:\GD32\GDproject\KeilTool
python -m keiltool.cli configure --project "C:\Path\To\App.uvprojx" --target App --probe stlink --backend gcc
```

然后重新打开生成的 `.code-workspace`。

## 10. 什么时候需要重新 `configure`？

这些情况建议重新运行：

- Keil target 变了。
- 源文件列表变了。
- include path 或 define 变了。
- 探针类型变了，例如 `stlink` 改成 `cmsis-dap`。
- `.axf/.elf` 路径变了。
- 换电脑或换工程路径。
- 删除了 `.keilbridge`。

只改 `.c/.h` 且后端是 GCC/CMake 时，通常只需要重新 `build`。

Debug-only 如果 `.axf` 路径不变，通常不用重新 `configure`。

## 11. ARMCC `.lib` 为什么会被提示风险？

Keil 工程里常见：

```text
arm_cortexM4lf_math.lib
```

这类 `.lib` 往往是 ARMCC/Keil 格式。GCC 不能保证直接链接。

处理思路：

- GCC 路线：换成 GCC 可用的源码库或 `.a`。
- ArmClang 路线：更可能兼容 Keil/Arm 格式。
- Debug-only 路线：不重新链接，所以不受这个问题影响。

## 12. 一进调试就 HardFault 怎么办？

先不要只看 `HardFault_Handler`。需要采集：

```text
PC / LR / MSP / PSP / xPSR
CFSR / HFSR / MMFAR / BFAR
异常栈帧里的原始 PC/LR
```

如果是 GCC/CMake 产物，先跑：

```powershell
python -m keiltool.cli doctor elf --project "xxx.uvprojx" --target App
```

重点看 `.init_array`、启动文件、链接脚本、RAM 段和 RTOS 中断入口。

## 13. CubeMX 工程支持吗？

支持识别和复用：

- `.ioc`。
- `Core/`。
- `Drivers/`。
- STM32 HAL。
- Keil target 中已有的 source/include/define。

KeilBridge 不调用 CubeMX，不改 `.ioc`，不改 `USER CODE`。

## 14. RTOS 工程支持吗？

当前策略是识别、诊断和对已验证组合做适配。

常见 RTOS 形态可以被识别，例如 FreeRTOS、RT-Thread、ThreadX、uCOS。涉及 ARMCC/RVDS port 到 GCC port 的工程，需要看具体项目诊断结果。

## 15. GD32 支持吗？

已有初步支持。GD32F303CB 已经过 DAPLink/CMSIS-DAP + OpenOCD 的最小工程验证。

其他 GD32 型号需要结合真实板卡、OpenOCD target、内存布局和启动文件继续验证。
