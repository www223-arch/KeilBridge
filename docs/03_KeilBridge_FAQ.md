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

## 7A. 只想采集 RTT，为什么还要导入 Keil 工程？

现在不需要。打开 `k2c gui` 后，可直接在 Device 输入框搜索内置设备目录中的精确型号，再启动 RTT。内置目录来自官方 CMSIS-Pack/PDSC；也可点击“导入”添加 `.pdsc`、`.pack` 或自定义 JSON。Keil 工程仍可用于自动带入 Target、芯片和内存信息，但不再是 GUI 硬件操作的前提。

如果芯片存在于目录中但按钮仍禁用，请查看“来源”和“解析”字段。CMSIS-Pack 不包含 OpenOCD target cfg；KeilBridge 只使用明确维护或用户显式提供的映射。没有映射、cfg 不存在或没有可写 RAM 时会明确报告缺失信息，不会根据相似型号猜一个 target。

也可完全不打开 GUI：

```powershell
k2c rtt --device GD32F303CC --format text
k2c rtt --device GD32F303CC --format jsonl
k2c rtt --device GD32F303CC --format raw > rtt.bin
k2c rtt --device STM32G431CBUx --vendor Keil --channel 1 --port 19022 --format raw --output "C:\Logs\foc_sweep.bin" --duration 8
```

`text/jsonl` 的采集内容写 stdout。raw 未指定 `--output` 时原样写 stdout；指定 `--output PATH` 后不做 UTF-8 或终端日志解析，使用至少 1 MiB 文件缓冲写入二进制文件。诊断、累计接收字节、文件字节、异常和断连信息写 stderr。`--channel 1` 选择独立的 RTT 上行通道 1，`--port` 选择本地 OpenOCD RTT TCP 端口。默认持续采集，按 `Ctrl+C` 会 flush/close 文件、清理 OpenOCD 并返回 `130`。

主机端的接收字节数与文件字节数不代表 MCU 端没有漏记录。FOC 扫频数据是否有效，仍须检查每条固定记录中的 timestamp 是否连续。

## 7B. 如何读取板子上的完整 Flash？

GUI 使用独立的“读取完整 Flash”按钮；CLI 可使用：

```powershell
k2c flash-read --device GD32F303CC --output board-flash.bin --output-format json
```

它读取设备目录或 Keil Target 中已验证的主用户 Flash 起始地址和完整容量，不包含 option bytes、OTP 或系统 ROM。为获得一致镜像，工具会记录当前状态并在必要时暂停内核，结束后仅恢复原本正在运行的目标，不执行复位。结果必须满足精确字节数，并报告 SHA-256；失败时可能保留部分文件作为证据，不应把部分文件当作完整备份。

## 7C. 为什么固件更新后 GUI 会询问 reload？

GUI 会记录所选 `.hex/.bin` 的路径、大小、修改时间和 SHA-256。外部编译完成后切回窗口，会对比磁盘版本并显示旧/新证据。接受后烧录新版本；拒绝后烧录按钮保持禁用，防止同一路径下实际内容已经变化却继续操作。重新选择该固件即可再次载入。点击“烧录并校验”时还会执行最终复核。

## 7D. 为什么操作没有弹出“成功”或“失败”窗口？

这是图形工作台的正常行为。右侧日志上方的“当前任务”区域会保留任务、阶段、耗时和最终结果；OpenOCD 执行和 RTT 采集使用活动进度条，不会根据等待时间伪造百分比。失败时界面自动切到 OpenOCD 输出，并提供“复制错误”和“打开日志”；复制内容包含结果摘要、OpenOCD 返回码和原始错误。只有烧录确认、固件 reload、安全关闭和设置保存等需要用户选择的步骤才使用对话框。

Windows 下由 GUI 启动的 OpenOCD 使用隐藏控制台窗口模式，因此每次检查连接、读取 Flash、烧录或采集 RTT 都不应再闪出终端。CLI 不使用这个 GUI 专属选项，标准输出、错误输出和退出码仍可被脚本或第三方工具读取。

## 8. GUI 中 RTT 与烧录为什么不能同时进行？

`k2c gui` 把“读取完整 Flash”“烧录并校验”和“开始 RTT”设计为独立操作，但它们都需要独占同一支 ST-Link/OpenOCD 会话。RTT 扫描、采集或停止清理期间，Flash 读取、烧录和连接检查会禁用；其他硬件操作期间，RTT 启动会禁用。

这是为了避免两个 OpenOCD 进程同时抢占 ST-Link，导致连接失败、日志混杂或把目标置于不可预期状态。需要烧录时，先点击“停止采集”，等待状态变为“RTT 已停止”后再操作。若界面提示“RTT 清理不完整”，再次点击“停止采集”完成清理；在清理完成前，关闭窗口和新的硬件操作都会被阻止。

## 9. GUI 的 RTT 会复位或停止 MCU 吗？

不会。GUI RTT 仅通过 `rtt setup`、`rtt start` 和 RTT TCP server 附着到 `SEGGER RTT` 控制块，不发送 reset、halt 或 resume 命令。自动模式扫描当前 Target 的 RAM；手动模式使用填写地址起始的 `0x100` 字节窗口。

如果找不到 RTT 控制块，确认当前固件已经包含并初始化 SEGGER RTT，检查所选设备或 Target 的 RAM 解析结果，或填写明确的控制块地址。RTT 文本会自动以 UTF-8 写入日志；有工程时默认根目录为 `<keil-project-root>\.keilbridge\logs\`，无工程时为 `%APPDATA%\KeilTool\logs\`，也可在 GUI 中修改并记忆。

RTT 页的“显示等级”使用固件现有的 EasyLogger/SEGGER RTT 等级语义。默认 `VERBOSE` 显示全部；选择 `INFO` 会显示 `ASSERT`、`ERROR`、`WARN` 和 `INFO`。筛选和“清空显示”只处理最近 20,000 行 GUI 缓存，完整 UTF-8 日志仍持续记录所有等级。

## 9B. VOFA+ 能通过 RTT 向 MCU 发送命令吗？

可以。“VOFA+ 曲线”使用同一个全双工 TCP 连接：MCU 的用户所选 RTT curve up-channel 经过 KeilTool 转发到 VOFA+，VOFA+ 发送区的数据经过 KeilTool 原样写入用户所选 RTT down-channel。文本模式是否追加换行由 VOFA+ 的发送设置决定；HEX 模式发送精确字节。KeilTool 不进行 UTF-8 转换、命令拆包或自动补帧，并把下行原始字节保存到会话目录的 `vofa-to-mcu.bin`。

固件必须配置与工作台一致的 down-channel，并在主循环或任务中调用对应的 `SEGGER_RTT_Read(channel, ...)`。不要在高频 ISR 中阻塞等待命令。KeilTool 不规定名称和业务协议；TCP 写入成功不等于命令执行成功，需要可靠控制时由固件协议自行提供序号、校验和 ACK。

最短操作步骤：

1. 在 KeilTool 高级设置中填写曲线 Up、反向 Down 及各自 OpenOCD 端口；名称校验可留空。点击“VOFA+ 曲线”，等待界面显示 RTT 与 VOFA 已连接。
2. 在 VOFA+ 中使用 KeilTool 显示的 TCP Client 地址连接，协议引擎选择 `JustFloat`。
3. 发送二进制协议时，在底部发送区启用 `HEX`/十六进制发送，以空格分隔输入完整字节，例如 `B1 50 ... CRC_LO CRC_HI`。
4. 将发送区的“自动追加”设为“不追加/无”，不要追加 `\n`、`\r` 或 `\r\n`；同时关闭循环发送，除非协议明确需要周期命令。

文本发送模式会按 VOFA+ 当前编码（通常为 UTF-8）把字符转换成字节，并可能受“自动追加”设置影响，因此不适合发送含 `0x00` 或任意二进制值的控制帧。HEX 模式下输入的每个字节会原样进入 KeilTool，KeilTool不会添加换行、编码或帧头。VOFA+ 官方文档也区分字符串发送与十六进制字节发送；其发送区支持自动追加 `\n`、`\r`、`\r\n`、`\n\r`，二进制协议应选择不追加。

TCP 与 RTT 都是字节流：KeilTool 保证字节内容、顺序和方向不变，但一次 VOFA“发送”可能被拆成多次 RTT 读取，也可能与下一次发送合并。MCU 必须使用流式解析器按帧头、长度和校验重新组帧，不能把一次 `SEGGER_RTT_Read` 当作一帧。曲线 Up 数据只发送到 VOFA 的接收方向，VOFA 下行字节只进入所选 RTT Down，两者不会相互拼接。

## 9C. 打开 VOFA+ 曲线后，文字 RTT 还能同时接收吗？

可以。默认配置下，KeilTool 在同一个 OpenOCD 进程中同时启动 `channel 0 / 127.0.0.1:19021` 和 `channel 1 / 127.0.0.1:19022` 两个 RTT server。这里的 TCP 只是在电脑本机连接 OpenOCD 与 KeilTool，不是 MCU 网络通信。Channel 0 解析、显示、按等级过滤并保存文字日志；Channel 1 进入 JustFloat 和 VOFA+。两者的通道与端口都可配置，但文字 Up 和曲线 Up 必须不同，保证物理隔离。

固件必须遵守本次会话中选择的通道：文字只写文字 Up，曲线只写曲线 Up。通道名称校验是可选的，未填写名称时 KeilTool 不作假设。如果把文字写进曲线通道，KeilTool 会报告 JustFloat 无效帧，而不会尝试根据内容自动过滤。

## 10. GUI 提示 target 未验证或 target override 无效怎么办？

GUI 只会在 OpenOCD target cfg 已验证时启用“检查连接”“烧录并校验”和 RTT。自动解析失败时，不会猜测 target cfg。可在高级设置填写 override，但它必须是存在的 `.cfg` 文件：相对路径必须位于 OpenOCD scripts 目录内，绝对路径必须指向存在的文件。

检查 Keil Target 的芯片信息、OpenOCD/scripts 路径以及 cfg 文件本身。修正后重新解析 Target；在验证成功前请不要改用不相关的 cfg 强行烧录。

## 11. ST-Link 被占用或 GUI 无法连接怎么办？

先停止 GUI 内的 RTT 或烧录任务，并等待状态回到空闲。随后关闭 Keil、STM32CubeProgrammer、VS Code/Cortex-Debug、串口监视器，以及可能持有探针的其他 OpenOCD/GDB 会话。必要时在任务管理器结束确认不再使用的 `openocd.exe` 和 `arm-none-eabi-gdb.exe`，重新插拔 ST-Link，再使用 GUI 的“检查连接”。

不要在 RTT 采集期间手工启动第二个 OpenOCD，也不要用多个 GUI 实例连接同一支 ST-Link。连接或烧录失败时，先查看 GUI 输出中的命令和日志路径。每个任务都保存在 `时间_芯片_任务` 独立目录中，`session.json` 可用于确认 target、开始/结束时间和执行结果。

## 12. `CMSIS-DAP command mismatch` 怎么办？

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

## 13. `preLaunchTask "CMake: build" 已终止` 怎么办？

这通常是旧生成文件依赖 PATH 中的 `cmake`，但 VS Code task 环境找不到。

处理：

```powershell
cd D:\GD32\GDproject\KeilTool
python -m keiltool.cli configure --project "C:\Path\To\App.uvprojx" --target App --probe stlink --backend gcc
```

然后重新打开生成的 `.code-workspace`。

## 14. 什么时候需要重新 `configure`？

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

## 15. ARMCC `.lib` 为什么会被提示风险？

Keil 工程里常见：

```text
arm_cortexM4lf_math.lib
```

这类 `.lib` 往往是 ARMCC/Keil 格式。GCC 不能保证直接链接。

处理思路：

- GCC 路线：换成 GCC 可用的源码库或 `.a`。
- ArmClang 路线：更可能兼容 Keil/Arm 格式。
- Debug-only 路线：不重新链接，所以不受这个问题影响。

## 16. 一进调试就 HardFault 怎么办？

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

## 17. CubeMX 工程支持吗？

支持识别和复用：

- `.ioc`。
- `Core/`。
- `Drivers/`。
- STM32 HAL。
- Keil target 中已有的 source/include/define。

KeilBridge 不调用 CubeMX，不改 `.ioc`，不改 `USER CODE`。

## 18. RTOS 工程支持吗？

当前策略是识别、诊断和对已验证组合做适配。

常见 RTOS 形态可以被识别，例如 FreeRTOS、RT-Thread、ThreadX、uCOS。涉及 ARMCC/RVDS port 到 GCC port 的工程，需要看具体项目诊断结果。

## 19. GD32 支持吗？

已有初步支持。GD32F303CB 已经过 DAPLink/CMSIS-DAP + OpenOCD 的最小工程验证。

其他 GD32 型号需要结合真实板卡、OpenOCD target、内存布局和启动文件继续验证。
