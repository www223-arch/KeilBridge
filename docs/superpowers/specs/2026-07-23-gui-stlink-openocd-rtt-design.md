# KeilTool GUI：ST-Link 整包烧录与 RTT 日志采集设计

日期：2026-07-23
状态：已批准

## 1. 目标

为 KeilTool 增加一个 Windows 桌面 GUI，通过 ST-Link 和 OpenOCD 完成两项彼此独立的工作：

1. 选择现成的 `.hex` 或 `.bin` 整包，执行烧录、校验和复位。
2. 附加到正在运行的 MCU，通过 OpenOCD RTT server 实时显示并保存 RTT 日志。

GUI 使用 Python 标准库 Tkinter，通过 `k2c gui` 启动，不新增 Qt、Web 服务或 J-Link 依赖。

## 2. 范围

### 2.1 本期包含

- 选择 Keil `.uvprojx` 工程和工程内 Target。
- 从 Keil 工程解析 Device、RAM、Flash，并调用现有 OpenOCD target resolver。
- 固定使用 `interface/stlink.cfg` 和 SWD。
- 选择已有 `.hex` 或 `.bin` 整包。
- `.hex` 使用文件自带地址；`.bin` 默认从 `0x08000000` 烧录，地址可编辑并记忆。
- 烧录必须执行 `program`、`verify`、`reset`，并保存 OpenOCD 原始输出。
- RTT 自动扫描 Keil 推导出的 RAM 范围，也允许手工指定 `_SEGGER_RTT` 控制块地址。
- RTT 启动时不复位 MCU，不提供“采集前复位”选项。
- RTT 通道默认使用通道 0；GUI 实时显示日志并自动写入 UTF-8 文件。
- 记忆上次使用的工程、Target、固件、BIN 地址、OpenOCD 路径、scripts 路径、target override、RTT 参数和日志目录。
- 烧录与 RTT 探针访问互斥。

### 2.2 本期不包含

- 调用 Keil 构建、合并或生成整包。
- J-Link、CMSIS-DAP、DAPLink 或 pyOCD 后端。
- 多探针并行烧录。
- RTT 下行通道输入。
- 多 RTT 通道同时采集。
- 固件历史库、批量生产烧录、序列号写入或加密。
- 自动安装 OpenOCD 或 USB 驱动。

## 3. 用户界面

主窗口采用左右工作台布局。

### 3.1 左侧配置区

- Keil 工程文件选择。
- Target 下拉框。
- 只读显示 Device、Flash、RAM、解析出的 OpenOCD target 和解析依据。
- 整包文件选择，仅接受 `.hex` 和 `.bin`。
- BIN 起始地址输入；选择 HEX 时禁用。
- “检查连接”和“烧录并校验”按钮。
- RTT 自动扫描/手工地址模式。
- RTT 控制块地址、通道、日志目录。
- “开始采集”和“停止采集”按钮。
- 可折叠高级设置：OpenOCD 可执行文件、scripts 目录、target cfg override、RTT TCP 端口和扫描超时。

### 3.2 右侧输出区

- “RTT 日志”标签页：实时文本、采集时长、接收字节数/行数、清空显示和打开日志目录。
- “OpenOCD 输出”标签页：连接检查、烧录和 RTT server 的原始输出。
- 底部状态栏：`空闲`、`检查连接`、`烧录中`、`RTT 扫描中`、`RTT 采集中`、`停止中`、`失败`。

### 3.3 启动行为

GUI 启动时恢复上次配置，但不自动连接、不自动烧录，也不自动启动 RTT。所有硬件操作必须由用户点击触发。

## 4. 架构

GUI 是薄界面层，硬件操作放入可独立测试的核心服务。

### 4.1 OpenOCD 配置解析

配置解析器负责：

- 解析 `.uvprojx` 和 Target。
- 查找 OpenOCD 及 scripts 目录。
- 固定选择 ST-Link interface。
- 使用现有 `resolve_openocd_target` 解析 target cfg。
- 手工 target override 优先于自动解析。
- 检查 target cfg 是否存在于当前 scripts 目录。

如果 target 无法确认或 cfg 不存在，连接、烧录和 RTT 按钮必须保持不可执行，并向用户报告原因。不得生成猜测性的 `target/gd32*.cfg`。

### 4.2 Flash 服务

Flash 服务接收结构化请求，构建参数数组并启动一次性 OpenOCD 进程，不通过 shell 拼接命令。

HEX：

```text
program <firmware.hex> verify reset exit
```

BIN：

```text
program <firmware.bin> <base-address> verify reset exit
```

成功必须同时满足：

- OpenOCD 进程返回码为 0。
- 输出中出现 program 完成证据。
- 输出中出现 verify 成功证据。

烧录前 GUI 显示确认框，包含 Device、target cfg、固件绝对路径、文件大小及 BIN 地址。失败时保存 stdout/stderr，并复用 Flash Doctor 的分类规则生成可读诊断。

### 4.3 RTT 服务

OpenOCD 官方 RTT 流程为：

```text
rtt setup <address> <size> "SEGGER RTT"
rtt start
rtt server start <port> <channel>
```

自动模式使用 Keil 工程推导出的主 RAM 起始地址和大小作为搜索范围。手工模式从指定控制块地址开始，使用 `0x100` 字节搜索范围。

启动流程：

1. 启动 OpenOCD 并连接目标，不执行 reset。
2. 配置 RTT 搜索范围并执行 `rtt start`。
3. 启动指定通道的本地 TCP server。
4. 等待 OpenOCD 报告发现 RTT 控制块，并重试连接本地 TCP server。
5. GUI 连接成功后读取已有 RTT 缓冲数据并持续采集新增数据。
6. 使用增量 UTF-8 解码器显示文本；非法字节替换为 Unicode replacement character，同时保留 OpenOCD 证据日志。

“完整日志”指连接成功时 RTT 缓冲区仍保留的内容和其后的全部输出。连接前已经被固件覆盖的历史日志无法恢复。

停止流程：

1. 停止接收并关闭 TCP socket。
2. 刷新并关闭 UTF-8 日志文件。
3. 正常终止 OpenOCD。
4. 超时后才强制结束进程。

OpenOCD RTT 命令依据：[OpenOCD User's Guide - Real Time Transfer](https://openocd.org/doc/html/General-Commands.html#Real-Time-Transfer-_0028RTT_0029)。

### 4.4 配置记忆

配置保存在：

```text
%APPDATA%\KeilTool\gui-settings.json
```

保存使用 UTF-8 JSON 和原子替换，避免进程中断留下半个文件。无效、缺失或版本不兼容的配置不得阻止 GUI 启动，而是回退默认值并在 OpenOCD 输出页记录提示。

### 4.5 并发模型

- Tk 主线程只处理界面。
- OpenOCD 进程读取、烧录等待和 RTT socket 读取均在后台线程。
- 后台线程通过线程安全队列发送结构化事件。
- Tk 主线程使用 `after()` 定时消费事件并更新控件。
- 关闭窗口时必须先停止活动任务，再销毁窗口。

## 5. 状态与互斥

同一个 ST-Link 同时只允许一个硬件任务。

- RTT 采集中禁止连接检查和烧录。
- 烧录或连接检查中禁止启动 RTT 和修改相关配置。
- 用户尝试冲突操作时显示明确提示，不自动杀死当前进程。
- 烧录不会自动启动或停止 RTT。
- RTT 不会自动触发烧录。

状态转换由单独的会话状态对象控制，不能仅依赖按钮是否禁用。

## 6. 日志与错误处理

默认日志目录位于所选 Keil 工程根目录：

```text
.keilbridge/logs/
```

允许用户覆盖并记忆。文件按时间命名：

```text
flash_<target>_<timestamp>.out.log
flash_<target>_<timestamp>.err.log
rtt_<target>_<timestamp>.log
rtt_openocd_<target>_<timestamp>.out.log
rtt_openocd_<target>_<timestamp>.err.log
```

必须区分并报告：

- OpenOCD 不存在或版本不可执行。
- scripts 目录或 ST-Link interface 不存在。
- OpenOCD target 无法确认。
- Keil RAM 信息缺失，无法自动扫描 RTT。
- 固件扩展名无效、文件不存在、BIN 地址无效。
- ST-Link 未连接、被其他程序占用或目标无供电。
- program 失败、verify 失败或 reset 失败。
- RTT 控制块超时未找到。
- RTT TCP 端口被占用或连接失败。
- OpenOCD 或 RTT socket 意外断开。

错误提示必须包含日志路径和可复制的 OpenOCD 命令预览，但 GUI 不把命令交给 shell 执行。

## 7. 测试策略

### 7.1 单元测试

- HEX/BIN OpenOCD 参数构建和路径转义。
- BIN 地址解析与边界检查。
- target 自动解析、override 和“无法确认”阻断。
- 配置保存、恢复、损坏回退和版本迁移。
- 会话状态转换与烧录/RTT 互斥。
- OpenOCD program/verify 成功与失败判定。
- RTT 控制块发现、超时、增量 UTF-8 解码和停止清理。

### 7.2 集成测试

- 使用假 OpenOCD 可执行程序模拟 stdout、stderr、退出码和长驻进程。
- 使用本地 TCP server 模拟 RTT 分片、中文 UTF-8、断线和空数据。
- 验证 GUI 关闭时后台线程和子进程不残留。

### 7.3 实机验收

- 使用真实 ST-Link 和可确认 target 的 Keil 工程执行只读连接检查。
- 分别烧录一个 HEX 整包和一个带明确地址的 BIN 整包。
- 两次烧录均出现 program 完成和 verify 成功证据。
- 在不复位 MCU 的前提下找到 `SEGGER RTT` 控制块。
- RTT 连续采集至少 60 秒，界面与 UTF-8 日志内容一致。
- RTT 采集中烧录按钮不可用；停止后恢复可用。
- 关闭 GUI 后确认没有残留 OpenOCD 进程。

## 8. 验收标准

- `k2c gui` 可启动 Tkinter 工作台。
- 首次使用可完成工程、Target、固件和 OpenOCD 配置。
- 第二次启动可恢复全部非敏感配置。
- target 无法确认时不会执行硬件操作。
- HEX/BIN 烧录均进行 verify，失败不会显示成功。
- RTT 与烧录完全独立且互斥。
- RTT 启动不复位目标。
- RTT 日志实时显示并自动保存为 UTF-8。
- 自动化测试通过，实机证据和日志路径可追溯。
