# KeilTool GUI 主题与 RTT 等级过滤设计

日期：2026-07-24
状态：已确认

## 1. 目标

在不改变现有左右分栏和操作流程的前提下：

1. 将 Tkinter GUI 统一为浅色工业风，提升层级、状态辨识度和日志可读性。
2. 按 SEGGER RTT 虚拟 Terminal 与 EasyLogger 原生等级解析日志。
3. 提供日志等级阈值过滤，只影响 GUI 显示，不影响完整日志落盘。

本次不增加关键词过滤、正则过滤、布局重构、主题切换或新的烧录流程。

## 2. 已确认的日志语义

SEGGER RTT Channel 0 使用 `0xFF` 加 Terminal ID 字节切换虚拟 Terminal。项目中的 EasyLogger 将日志等级映射为：

| EasyLogger 等级 | 数值 | RTT Terminal |
| --- | ---: | ---: |
| ASSERT | 0 | 0 |
| ERROR | 1 | 0 |
| WARN | 2 | 0 |
| INFO | 3 | 0 |
| DEBUG | 4 | 1 |
| VERBOSE | 5 | 2 |

Terminal 0 同时承载 ASSERT、ERROR、WARN、INFO，因此不能只依靠 Terminal ID 判断等级。解析优先级为：

1. EasyLogger ANSI 等级颜色与等级前缀；
2. Terminal 1 推断为 DEBUG，Terminal 2 推断为 VERBOSE；
3. 其余未识别文本按 INFO 处理。

参考：

- SEGGER RTT：<https://kb.segger.com/RTT>
- SEGGER J-Link RTT Viewer：<https://kb.segger.com/J-Link_RTT_Viewer>
- 项目 EasyLogger 映射：`D:\D3Spi\dragonfoucs330\04_Software\01_Source_Code\Middleware\easylogger`

## 3. 数据流

采集链路调整为：

```text
OpenOCD RTT TCP 字节流
  -> SEGGER Terminal 控制序列解析
  -> UTF-8 增量解码
  -> EasyLogger ANSI/前缀等级识别
  -> 完整文本日志落盘
  -> 结构化日志事件
  -> GUI 等级阈值过滤与着色
```

解析器必须保持跨数据块状态，正确处理：

- `0xFF` 与 Terminal ID 分处两个 TCP 数据块；
- UTF-8 多字节字符跨数据块；
- ANSI 控制序列跨数据块；
- 一行文本跨多个数据块；
- 采集结束时尚未换行的尾部文本。

控制序列不作为可见文字输出。无法确认的尾部内容按普通文本保留，不得静默丢弃。

## 4. 结构化日志模型

新增日志等级枚举：

```text
ASSERT < ERROR < WARN < INFO < DEBUG < VERBOSE
```

每条 GUI 日志记录至少包含：

- `level`：识别出的 EasyLogger 等级；
- `text`：去除 SEGGER Terminal 控制字节后的文本；
- `terminal`：产生该文本时的 Terminal ID；
- `style`：由等级映射出的 GUI 标签名。

完整日志文件记录所有等级的文本。等级过滤只作用于 GUI，不改变 RTT 会话、TCP 读取和日志文件内容。

## 5. 等级阈值

工具栏提供单选下拉框：

```text
VERBOSE / DEBUG / INFO / WARN / ERROR / ASSERT
```

阈值含义为显示所选等级及更严重等级。例如：

- VERBOSE：显示全部；
- INFO：显示 ASSERT、ERROR、WARN、INFO；
- WARN：显示 ASSERT、ERROR、WARN；
- ERROR：显示 ASSERT、ERROR。

默认值为 VERBOSE。切换阈值后立即重绘当前 GUI 缓存，不中断采集。

GUI 缓存最多保留最近 20,000 行。达到上限后删除最旧记录；完整历史仍保存在日志文件中。

“清空显示”清空 GUI 缓存和当前文本区域，不删除日志文件，也不停止采集。

## 6. 视觉主题

保持现有控件位置和工作流，应用以下浅色工业配色：

| 用途 | 颜色 |
| --- | --- |
| 主背景 | `#F3F5F7` |
| 操作区背景 | `#FFFFFF` |
| 边界 | `#D7DEE5` |
| 主文字 | `#202A33` |
| 次要文字 | `#657481` |
| 主操作 | `#087F8C` |
| 成功 | `#15803D` |
| 警告 | `#B36B00` |
| 错误 | `#B42318` |

RTT 日志使用等宽字体，等级颜色保持克制：

- ASSERT：洋红；
- ERROR：红；
- WARN：琥珀；
- INFO：蓝青；
- DEBUG：绿；
- VERBOSE：灰蓝。

不使用整行高饱和背景。输入框、按钮、Notebook、状态栏统一字体、边距、焦点态和禁用态。

RTT 工具栏新增：

- “显示等级”下拉框；
- 当前阈值；
- 可见行数与缓存总行数；
- 现有清空和打开日志目录操作。

## 7. 设置记忆

`GuiSettings` 新增 RTT 显示等级字段：

- 默认 `VERBOSE`；
- 仅接受六个已知等级；
- 无效或旧版本设置回退到默认值；
- 关闭 GUI 时沿用现有设置保存流程。

本次不改变设置文件位置和现有字段语义。

## 8. 错误处理

- 未知 Terminal ID：保留 Terminal 状态为未知，文本按 INFO 显示。
- 非法或不完整 UTF-8：沿用替换字符策略，不终止采集。
- 不完整 ANSI 序列：等待后续数据；会话结束时按普通文本输出。
- 无 EasyLogger 等级的普通 RTT 文本：按 INFO 显示。
- GUI 重绘失败不得影响 RTT 文件落盘和会话清理。

## 9. 测试

测试先行覆盖：

1. Terminal 控制序列完整与跨包解析；
2. UTF-8、ANSI、日志行跨包；
3. 六种 EasyLogger 等级识别；
4. Terminal 1/2 回退等级；
5. 普通 RTT 文本按 INFO 处理；
6. 六个阈值边界；
7. 过滤不影响完整日志；
8. 阈值切换即时重绘；
9. 20,000 行缓存上限；
10. 设置默认值、持久化和无效值回退；
11. GUI 创建、关闭和高频 RTT smoke；
12. 1280x800 与 1024x720 下无文字重叠或控件溢出。

## 10. 验收标准

- GUI 布局保持不变，视觉主题符合浅色工业风。
- RTT 控制字节不再显示为乱码。
- 等级阈值严格使用 SEGGER/EasyLogger 已有语义。
- 默认 VERBOSE 显示全部日志。
- GUI 过滤不丢失日志文件中的任何等级。
- 长时间采集时 GUI 缓存保持有界。
- 自动化测试、编译检查、CLI smoke 和 GUI 启停 smoke 通过。
