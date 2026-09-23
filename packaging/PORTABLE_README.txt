KeilTool ST-Link 便携版
======================

启动
----
双击 KeilTool-STLink.exe。无需安装 Python，也不依赖源码目录或固定盘符。

普通 RTT 采集
------------
1. 导入 Keil 工程，或选择“独立 Device”中的准确芯片型号。
2. 在“使用的 ST-Link”中点击“刷新”，选择对应调试器；可点击“命名”改成容易辨认的名称。
3. 确认日志目录和文字 RTT Up 通道。
4. 点击“开始采集”。RTT 采集不会主动复位或暂停目标。

使用 VOFA+ 曲线时，VOFA+ 需要另行安装；首次点击“VOFA+ 曲线”时选择 vofa+.exe 即可。

环境要求
--------
- Windows 10/11 x64。
- ST-Link 驱动可正常识别探针；设备管理器中应能看到 STM32 STLink。
- 目标板已供电并启用 SEGGER RTT。

首次使用但系统无法识别 ST-Link 时，双击包内的 ST-LINK-Driver-Official.url，
从 STMicroelectronics 官方页面下载并安装 STSW-LINK009。该官方驱动支持
ST-LINK/V2、ST-LINK/V2-1 和 STLINK-V3；下载时需由使用者接受 ST 的许可与
出口合规条款，因此便携包不直接转载驱动安装文件。

便携包已经包含 OpenOCD、scripts 和内置芯片目录。没有收录的芯片可在界面中导入 CMSIS-Pack/PDSC，或选择经过确认的 OpenOCD target override。

设置与日志
----------
用户设置、调试器别名和无工程时的默认日志保存在：
%APPDATA%\KeilTool\

选择 Keil 工程时，默认日志保存在工程目录的 .keilbridge\logs\。

安全提示
--------
“检查连接”和 RTT 采集不会下载固件。“烧录并校验”会改写目标 Flash 并在完成后复位目标，请确认固件、芯片和“使用的 ST-Link”名称后再执行。
