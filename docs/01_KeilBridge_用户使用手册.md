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

这条路线不编译、不下载固件，只用 Keil 产物做符号调试。换句话说，Debug-only 的固件来源仍然是 Keil IDE、Keil 命令行或项目原有构建链路；KeilBridge 只接管 OpenOCD/GDB/VS Code 调试入口和诊断报告。

KeilBridge 也提供了 Keil 命令行封装，用户不需要记住 `UV4.exe` 参数：

```powershell
python -m keiltool.cli keil build --project "C:\Path\To\App.uvprojx" --target App
python -m keiltool.cli keil rebuild --project "C:\Path\To\App.uvprojx" --target App
python -m keiltool.cli keil download --project "C:\Path\To\App.uvprojx" --target App
```

`build/rebuild` 优先调用 Keil `UV4.exe`；如果当前机器找不到 `UV4.exe`，但工程目录里有 Keil 生成的 `<target>.BAT`，KeilBridge 会运行一份 `.keilbridge/generated/keil-batch/` 下的副本作为 fallback，不修改原 `.BAT`。`download` 需要 Keil `UV4.exe`，因为它依赖 Keil target 里的 Flash Download 配置。

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

Debug-only 的典型流程是：

1. 先用 Keil IDE、Keil 命令行、KeilBridge 的 `keil build/rebuild`，或项目原有脚本编译工程，生成带调试符号的 `.axf/.elf`。
2. 如果目标板上还没有这份固件，先用 Keil 下载、KeilBridge 的 `keil download`，或原项目已有下载方式下载。
3. 再让 KeilBridge 生成 debug-only 工作区，使用同一个 `.axf/.elf` 作为符号文件进行 VS Code/OpenOCD/GDB 调试。

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

注意：这两个入口都不会把 `.axf/.elf` 下载进芯片。它们只使用 `.axf/.elf` 里的符号信息来解释当前芯片里已经存在的程序。如果重新编译了 Keil 工程，通常需要先确保新固件已经下载到板子，再开始 debug-only 调试。

## 4. 烧录和调试前诊断

### 4.1 Flash Doctor

```powershell
python -m keiltool.cli doctor flash --project "C:\Path\To\Project\MDK-ARM\App.uvprojx" --target App --probe stlink --run
```

它会检查：

- OpenOCD 是否能启动。
- 探针是否能连接目标芯片。
- reset/halt 后 PC/MSP 的原始值及其是否落入工程声明的 Flash/RAM 范围。
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

### 4.4 ST-Link 烧录和 RTT 图形工作台

启动图形工作台：

```powershell
k2c gui
```

如果正在工具源码目录中直接运行，可使用等价命令：

```powershell
python -m keiltool.cli gui
```

启动时不会访问 ST-Link、复位 MCU、烧录或启动 RTT。工作台会恢复上一次关闭时保存的非敏感设置；设置文件位于：

```text
%APPDATA%\KeilTool\gui-settings.json
```

Keil 工程在图形工作台中是可选的。“配置来源”明确区分 `Keil 工程` 和 `独立 Device`，两种来源不会混用。工程模式中的 Device、Target、Flash/RAM 和固件属于当前工程上下文；切到独立 Device 后，工程 Target 和工程固件立即退出活动配置，再从目录选择精确芯片和对应固件。切回工程模式时重新解析并恢复此前的工程 Target。两种模式及各自固件、芯片选择、OpenOCD 路径和自定义日志根目录都会在关闭时记住。

内置设备目录由仓库中的官方 GigaDevice、STMicroelectronics CMSIS-Pack/PDSC 快照生成，记录来源、版本、core、FPU、Flash/RAM 和 flash algorithm。点击 Device 旁的“导入”可添加 `.pdsc`、`.pack` 或自定义 JSON；用户文件保存在 `%APPDATA%\KeilTool\devices\`，同厂商同型号的用户条目优先于内置条目。PACK 只读取其中的 PDSC，不解压到磁盘。损坏或不安全的导入会被拒绝，不影响已有目录。

CMSIS-Pack 本身不提供 OpenOCD target cfg。KeilBridge 只为已明确维护的兼容系列填写 target；没有映射的芯片仍可查看信息，但硬件按钮保持禁用。可在高级设置中指定 OpenOCD、scripts 目录和 target override。override 必须是实际存在的 `.cfg` 文件：相对路径必须位于 scripts 目录内，绝对路径必须指向现有文件。任何无法验证、文件缺失或越出 scripts 目录的配置都会阻止“检查连接”“读取完整 Flash”“烧录并校验”和 RTT，而不是猜测芯片类型继续执行。

烧录区只接受已经生成的 `.hex` 或 `.bin` 文件，不负责编译、合并或从 `.axf/.elf` 转换固件：

- `.hex` 使用文件内嵌地址，BIN 基地址输入框不参与烧录。
- `.bin` 使用可编辑的 BIN 基地址，默认值为 `0x08000000`。
- “烧录并校验”要求 OpenOCD 同时给出程序写入和校验成功证据；成功日志通常包含 `Programming Finished` 与 `Verified OK`。
- 已选择的固件被外部编译器更新后，窗口回到前台时会显示旧/新文件大小、修改时间和 SHA-256，并询问是否 reload。选择“否”会把固件标记为过期并禁用烧录；重新选择文件或接受后才恢复。点击烧录时还会再校验一次，防止检查后文件再次变化。

“检查连接”“读取完整 Flash”和“烧录并校验”是独立动作。“检查连接”不下载固件。“读取完整 Flash”读取已验证的主用户 Flash，不读取 option bytes、OTP 或系统 ROM；为保证镜像一致，它会记录目标运行状态，必要时暂停内核，读取后仅在目标原本运行时恢复运行，且不复位。“烧录并校验”会改写 Flash，且完成后会按 OpenOCD 烧录命令复位目标。

RTT 也是独立动作。点击“开始 RTT”后，工作台在 Keil Target 或所选目录芯片的可写 RAM 范围中寻找 `SEGGER RTT` 控制块并附着到 RTT TCP 通道；该流程不包含 reset、halt 或 resume，因此不会为了采集 RTT 主动改变 MCU 运行状态。自动扫描使用已验证的 RAM 范围；选择手动地址时只搜索该地址起始的 `0x100` 字节窗口。

RTT 页会解析 SEGGER 虚拟 Terminal，并优先使用 EasyLogger 已有的 `ASSERT`、`ERROR`、`WARN`、`INFO`、`DEBUG`、`VERBOSE` 等级，不由 GUI 重新定义日志等级。“显示等级”是严重度阈值：例如选择 `INFO` 时显示 `ASSERT` 到 `INFO`，隐藏 `DEBUG` 和 `VERBOSE`。默认值为 `VERBOSE`，关闭工作台时会记住当前阈值；切换阈值会立即重绘最近 20,000 行 GUI 缓存，不会中断 RTT。

Flash 读取、烧录、连接检查和 RTT 共享同一支 ST-Link，但任何时刻只允许一个操作拥有它。RTT 正在扫描、采集或停止清理时，其他硬件动作会禁用；Flash 读取、烧录或连接检查进行时，RTT 启动和配置编辑会禁用。

右侧日志页上方的“当前任务”区域持续显示任务名称、明确的执行阶段、耗时和最终结果。参数准备、结果分析等可验证阶段使用阶段进度；OpenOCD 执行和 RTT 扫描/采集使用活动进度条，不按时间虚构完成百分比。普通成功和失败不会反复弹出对话框：成功结果保留在绿色状态中，失败结果保留在红色状态中并自动切到 OpenOCD 输出，可点击“复制错误”取得摘要、返回码和原始错误，也可点击“打开日志”进入本次任务目录。只有烧录确认、固件 reload、安全关闭和设置保存等确实需要决定的流程才弹窗。

Windows GUI 启动的 OpenOCD 进程使用后台窗口模式，连接检查、Flash 读取、烧录和 RTT 期间不会额外弹出终端窗口。该策略只作用于 GUI；CLI 仍保持标准 stdout/stderr 和中断处理，便于脚本、AI 自动化调试和第三方工具集成。

RTT 区域的“VOFA+ 曲线”按钮提供一键双向 JustFloat 桥接。一个 OpenOCD 进程会同时开放两个仅限本机的 RTT TCP server：up-channel 0 使用 `127.0.0.1:19021`，继续由 KeilTool 解析文字等级、显示并保存日志；up-channel 1 使用 `127.0.0.1:19022`，只把原始 JustFloat 数据交给 VOFA bridge。bridge 在 `127.0.0.1:1347` 等待 VOFA+ TCP 客户端，并启动已记忆的 VOFA+。首次使用时如果没有找到 `vofa+.exe`，工作台会要求选择一次，关闭时自动保存路径。该 VOFA TCP 连接同时承载发送区到 MCU RTT down-channel 1 的反向数据。

曲线模式不会 reset、halt 或 resume MCU。通道隔离是严格的：只有 channel 0 进入文字解析和等级过滤，只有 channel 1 原始字节进入 JustFloat 解码与 VOFA；工具不会从混合内容中猜测文字和曲线。工作台按 JustFloat 帧尾切分完整帧，在独立线程中转发，VOFA+ 未连接或绘制变慢不会阻塞 RTT 接收。转发队列满时只丢弃用于实时显示的完整帧，并显示文字、曲线、下行、丢弃和无效帧计数；文字日志写入本次会话的 RTT 日志，曲线上行原始字节写入 `rtt-justfloat.bin`。VOFA+ 发送区产生的每个原始字节都会不经 UTF-8 解码、不添加换行、不做命令封包地写入 RTT down-channel 1，并单独保存到 `vofa-to-mcu.bin`。MCU 需要把 down-channel 1 配置为 `ScopeCmd` 并调用 `SEGGER_RTT_Read(1, ...)`；主机发送成功只证明字节已交给 OpenOCD，不证明 MCU 已执行命令，可靠命令仍需由固件协议提供序号、校验和 ACK。停止采集会关闭 OpenOCD 和本地 TCP bridge，但不会强制关闭 VOFA+。

默认日志目录为：

```text
<keil-project-root>\.keilbridge\logs\
```

无工程时默认使用 `%APPDATA%\KeilTool\logs\`。可以在工作台中改为其他根目录，修改会被记住。每次连接、Flash 读取、烧录和 RTT 都创建独立目录：

```text
YYYYMMDD-HHMMSS-fff_<device>_<CONNECT|FLASH_READ|FLASH|RTT|RTT_VOFA>\
```

目录中包含任务日志、`openocd.stdout.log`、`openocd.stderr.log` 和 `session.json`；元数据写明开始/结束时间、芯片、任务、target cfg 和结果。RTT 通道完整内容保存在 `rtt.log`。等级过滤和“清空显示”只影响 GUI，不删除或截断完整日志。RTT 和 OpenOCD 文本区支持 `Ctrl+C`、右键复制/全选/复制全部，工具栏也可直接复制全部可见文本。

### 4.5 面向自动化的硬件 CLI

连接、烧录、完整 Flash 读取和 RTT 都可不打开 GUI。硬件来源必须二选一：Keil 工程加可选 Target，或设备目录中的精确 Device 加可选 Vendor。

```powershell
k2c connect --project "C:\Path\App.uvprojx" --target Debug --output-format json
k2c connect --device GD32F303CC --vendor GigaDevice --output-format json
k2c flash --device GD32F303CC --firmware "C:\Path\app.hex" --output-format json
k2c flash-read --device GD32F303CC --output "C:\Logs\GD32F303CC_flash.bin" --output-format json
k2c rtt --device GD32F303CC --format jsonl
k2c rtt --device STM32G431CBUx --vendor Keil --channel 1 --port 19022 --format raw --output "C:\Logs\foc_sweep.bin" --duration 8
k2c rtt --device GD32F303CC --channel 1 --port 19022 --format raw --output "C:\Logs\scope.bin" --vofa-listen 127.0.0.1:1347 --vofa-executable "C:\Tools\VOFA+\vofa+.exe"
```

`connect`、`flash` 和 `flash-read` 的 JSON schema 为 `keiltool.hardware.v1`，包含成功状态、设备、来源、target cfg、OpenOCD 返回码、证据日志和产物信息。`flash-read` 只有在输出文件字节数与主 Flash 容量完全一致时才成功，并返回 SHA-256；失败时保留已有的部分文件作为诊断证据。

RTT 默认持续采集到 `Ctrl+C`、RTT EOF 或错误，也可用 `--duration <秒>` 限时。`--format text` 输出解析后的日志，`jsonl` 输出 schema 为 `keiltool.rtt.v1` 的逐条记录；`raw` 不做 UTF-8 解码、换行或终端帧处理，原样处理 RTT TCP 字节。raw 未指定 `--output` 时仍写 stdout；指定 `--output PATH` 时使用至少 1 MiB 的主机文件缓冲直接写入该二进制文件，并抑制 raw stdout。输出文件在每次启动时截断，退出时 flush/close。OpenOCD 状态、累计接收字节数、最终文件字节数、异常和断连信息写 stderr。`Ctrl+C` 会清理 RTT/OpenOCD 后返回退出码 `130`。

`--channel 1` 可让 FOC 二进制记录独占 RTT 上行通道 1，`--port 19022` 指定 KeilTool 连接的本地 OpenOCD RTT TCP 端口。该采集命令只执行 `rtt setup`、`rtt start` 和 `rtt server start`，目标运行期间不发送 reset、halt 或 resume。主机字节计数只能证明 KeilTool 收到和写入了多少字节，不能检测 MCU 产生记录之前或 RTT 缓冲区内发生的漏记录；扫频有效性仍应由记录内 timestamp 连续性判定。

`--vofa-listen HOST:PORT` 把所选 Scope profile 上行通道中的完整 JustFloat 帧转发给连接到该地址的 VOFA+ TCP 客户端；必须与 `--format raw` 配合。VOFA 模式默认使用 profile 对应的 OpenOCD 端口，同时使用 `--text-port 19021` 连接 channel 0；channel 0 文字继续写入本次会话的 RTT 日志，但不会混入 raw stdout、`--output` 文件或 VOFA。该连接是全双工的：VOFA+ 发来的原始字节会透明写入 profile 约定的 RTT down-channel，并保存为本次会话的 `vofa-to-mcu.bin`。可选的 `--vofa-executable PATH` 会在监听成功后启动 VOFA+。命令结束时 stderr 额外报告上行帧、下行字节、丢弃、无效帧、反向错误和连接次数。

BilboPro 保留两个互不覆盖的 Scope profile：

- `bilbopro-imu-scope-v1`：默认 profile，Up1=`Scope`，15 路、200 Hz，OpenOCD `19022`，VOFA `1347`。
- `bilbopro-imu-loop-scope-v2`：闭环调试 profile，Up2=`LoopScope`，40 路、100 Hz，OpenOCD `19023`，VOFA `1348`；同时连接 Channel 1/`19022`，严格验证 Up1=`Scope`、Down1=`ScopeCmd` 并承载控制命令。

启动 LoopScope v2：

```powershell
k2c rtt --device <MCU型号> --format raw --scope-profile bilbopro-imu-loop-scope-v2 --vofa-listen 127.0.0.1:1348 --output loop-scope-v2.bin
```

GUI 高级设置中的“曲线配置”可在 v1/v2 之间切换并记忆选择；使用内置端口时，切换 profile 会同步切换 `1347/1348`。每次会话目录中的 `scope-channels.txt` 记录所选 profile 的完整字段映射和 `ScopeCmd` 控制帧合同。完整固定合同见 `docs/04_BilboPro_RTT_Scope协议.md`。

使用 v2 时，待 `LoopScope/ScopeCmd` 通道验证并连接后，RTT 区域会启用“控制命令”。该窗口按表单生成完整 ScopeCmd v1 帧，显示 profile、连接状态、seq、最终 HEX 和 I38/I39 ACK 提示。SET_SPEED 允许 `-6.5..+6.5 deg/s` 正反向目标；姿态 max_rate 为 `(0,6.5] deg/s`。START 始终需要显式确认。自动 KEEPALIVE 默认关闭，启用后显示续租倒计时，并在 RTT 断开、会话停止或窗口关闭时停止发送。所有下行帧仍写入本次会话的 `vofa-to-mcu.bin`。

高级覆盖参数在这些命令中保持一致：`--openocd`、`--scripts`、`--target-cfg` 和 `--logs-dir`。无法验证设备内存范围或 target cfg 时命令会失败，不会猜测配置继续访问硬件。

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
reset/halt 实测 PC/MSP 均位于工程声明的 Flash/RAM 范围
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
