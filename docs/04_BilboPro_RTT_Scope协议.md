# BilboPro RTT Scope 协议

## 1. 通道与端口

| 用途 | RTT channel | RTT 名称 | OpenOCD TCP | VOFA TCP |
| --- | ---: | --- | ---: | ---: |
| 文字日志 | Up0 | 固件现有名称 | 19021 | - |
| IMU Scope v1 | Up1 | `Scope` | 19022 | 1347 |
| IMU+Loop Scope v2 | Up2 | `LoopScope` | 19023 | 1348 |
| 控制命令 | Down1 | `ScopeCmd` | 19022 | 由 1347/1348 连接反向写入 |

所有 TCP 均绑定本机。KeilTool 不对 Down1 数据进行 UTF-8 转换、换行补齐或协议封装。

## 2. IMU Scope v1

频率 200 Hz。每帧为 `15 × float32 little-endian + 00 00 80 7F`，共 64 字节。I0-I14 映射保持既有 `bilbopro-imu-scope-v1` 合同不变。

## 3. IMU+Loop Scope v2

频率 100 Hz。每帧为 `40 × float32 little-endian + 00 00 80 7F`，共 164 字节。

I0-I14 与 v1 完全一致。I15-I39：

| 索引 | 字段 | 单位/说明 |
| ---: | --- | --- |
| I15-I18 | q6 w/x/y/z | 无量纲四元数 |
| I19-I22 | q9 w/x/y/z | 无量纲四元数 |
| I23-I26 | yaw target/feedback/error/output | deg/s |
| I27-I30 | pitch target/feedback/error/output | deg/s |
| I31 | control dt | ms |
| I32 | IMU sample age | ms |
| I33 | IMU samples dropped total | 累计计数 |
| I34 | I2C errors total | 累计计数 |
| I35 | RTT frames dropped total | 累计计数 |
| I36 | yaw error RMS, 2 s | deg/s |
| I37 | pitch error RMS, 2 s | deg/s |
| I38 | last command sequence | u8 值以 float32 精确回显 |
| I39 | last command result/status | `0` 成功；非零为结果/状态 bitmask |

I39 的具体 bit 位分配由 MCU 最终合同定义；KeilTool 当前只显示和转发，不臆造位值。

## 4. ScopeCmd v1

控制帧：

```text
B1 50 | ver:u8=1 | type:u8 | seq:u8 | len:u8(0..32) |
payload[len] | crc16_ccitt_false:u16 little-endian
```

CRC 覆盖从 SOF `B1 50` 到 payload 末字节。

| type | 命令 | payload |
| ---: | --- | --- |
| 01 | SET_MODE | axis:u8, mode:u8 |
| 02 | SET_SPEED | axis:u8, target_dps:f32LE，`[-6.5,+6.5] deg/s` |
| 03 | SET_PID | axis:u8, kp/ki/kd/output_limit_dps:f32LE |
| 04 | SET_ATTITUDE_QUAT | w/x/y/z:f32LE |
| 05 | SET_ATTITUDE_GAIN | kp/kd/max_rate_dps:f32LE，`max_rate_dps` 为 `(0,6.5]` |
| 06 | START | axis_mask:u8, ttl_ms:u16LE |
| 07 | KEEPALIVE | ttl_ms:u16LE |
| 08 | STOP | axis_mask:u8 |
| 09 | GET_STATE | 空 |

`axis=1` 表示 yaw/rotate，`axis=2` 表示 pitch。`mode=0/1/2` 分别表示 open-speed、closed-speed、quaternion-attitude。

START 必须显式发送，TTL 最大 30000 ms。KEEPALIVE 缺失或 TTL 到期时 MCU 必须立即停止相应运动。ACK 不得混入 Up1；v2 使用 I38 回显 seq，I39 返回结果和状态。

## 5. KeilTool 控制面板

GUI 高级设置选择 `bilbopro-imu-loop-scope-v2`，点击“VOFA+ 曲线”，待 Up2=`LoopScope`、Down1=`ScopeCmd` 均连接后，RTT 区域的“控制命令”按钮才会启用。面板显示当前 profile、Down1 连接状态、seq、参数表单以及含 CRC 的最终 HEX；支持 SET_MODE、SET_SPEED、SET_PID、SET_ATTITUDE_QUAT、SET_ATTITUDE_GAIN、START、KEEPALIVE、STOP、GET_STATE。

START 发送前必须再次确认。可选自动 KEEPALIVE 默认关闭，启用后立即发送一次，并按 TTL 的一半周期续租；界面显示下一次续租倒计时。RTT Down1 断开、会话停止或关闭命令窗口后，自动续租立即停止发送。

每次发送后以 LoopScope v2 的 I38/I39 判读 ACK：I38 必须等于该帧 seq，才表示 MCU 已处理到这条命令；I39=`0` 表示该 seq 成功，非零表示参数、CRC、状态或安全拒绝。I38 尚未更新时只能说明主机已把完整帧写入 RTT Down1，不能声称 MCU 已执行。
