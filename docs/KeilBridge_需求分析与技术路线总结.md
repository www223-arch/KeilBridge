# KeilBridge 需求分析与技术路线总结文档

> 主题：0 侵入式 Keil 工程迁移、CMake 多后端构建、GDB 自动化调试、AI 自动化测试闭环  
> 目标：明确 KeilBridge 的产品定位、核心需求、技术路线、系统架构和分阶段落地方案。

---

## 1. 项目背景

目前已有大量基于 Keil MDK 的嵌入式工程，包括：

```text
1. GD32 裸机工程
2. GD32 + RTOS 工程
3. STM32 标准库工程
4. STM32 + CubeMX/HAL 工程
5. 可能带有 FreeRTOS / RT-Thread / USB / FatFs / lwIP 等中间件的工程
6. 可能带有 ARMCC 专用语法或 Keil .lib 的老工程
```

传统 Keil 工作流的特点是：

```text
Keil IDE 负责：
    工程管理
    编译
    链接
    下载
    调试
    Watch
    Memory
    Register
    Call Stack
```

这种方式对人工调试很友好，但对 AI 自动化不友好。

KeilBridge 的目标不是单纯“把 Keil 换成 GCC”，而是：

```text
把 Keil 工程的编译、下载、调试、测试流程变成可脚本化、可诊断、可自动化、可被 AI 调用的流程。
```

---

## 2. 核心认知变化

最初目标可能是：

```text
Keil 工程 → CMake + GCC
```

经过分析后，更准确的目标应该是：

```text
Keil 工程
  ↓
非侵入式解析
  ↓
统一工程中间模型 IR
  ↓
多编译器后端生成
  ├─ GCC backend
  ├─ ArmClang backend
  └─ Keil backend / fallback
  ↓
统一调试后端
  ├─ OpenOCD + GDB
  ├─ J-Link GDB Server + GDB
  └─ pyOCD + GDB，可选
  ↓
结构化结果输出
  ├─ build_result.json
  ├─ doctor_result.json
  ├─ debug_result.json
  └─ test_report.md
  ↓
AI 自动分析与决策
```

最关键的结论是：

```text
真正重要的不是使用 GCC 还是 ArmClang；
真正重要的是能不能把 build / flash / debug / breakpoint / inspect / test 变成稳定的脚本化接口。
```

---

## 3. 产品定位

KeilBridge 不应该定位成：

```text
任何 Keil 工程都 0 成本转 GCC 的万能转换器
```

更合理的定位是：

```text
KeilBridge 是一个非侵入式 Keil 工程迁移、诊断与自动化调试工具。

它会尽量自动生成 CMake 构建系统；
能用 GCC 的工程走 GCC backend；
GCC 不兼容但更接近 Keil 生态的工程走 ArmClang backend；
实在无法迁移的工程保留 Keil backend；
所有失败都输出结构化诊断和修复建议。
```

一句话总结：

```text
KeilBridge = 迁移生成器 + 诊断器 + 多后端构建器 + GDB 自动化调试器 + AI 测试接口层
```

---

## 4. 核心需求分析

### 4.1 需求一：0 侵入式迁移

要求：

```text
1. 不修改用户原始 .c / .h / .s 文件
2. 不修改原始 .uvprojx / .uvoptx
3. 不移动用户目录结构
4. 不破坏原 Keil 工程
5. 所有生成文件放到 .keilbridge/ 或 generated/ 下
6. 所有兼容修改以 compat header 或 patch 形式输出
7. 所有自动判断都允许用户通过 board.override.yaml 覆盖
```

推荐生成目录：

```text
.keilbridge/
├─ generated/
│  ├─ CMakeLists.txt
│  ├─ cmake/
│  ├─ linker/
│  ├─ startup/
│  ├─ compat/
│  ├─ openocd/
│  ├─ jlink/
│  └─ vscode/
├─ build/
├─ report/
│  ├─ project_ir.json
│  ├─ doctor_result.json
│  ├─ doctor_report.md
│  ├─ build_result.json
│  ├─ debug_result.json
│  └─ test_report.md
└─ patches/
```

---

### 4.2 需求二：支持不同工程类型

需要适配：

```text
1. STM32 标准库工程
2. STM32 CubeMX/HAL 工程
3. STM32 LL 工程
4. GD32 标准库工程
5. 裸机工程
6. FreeRTOS 工程
7. RT-Thread 工程
8. 带 Bootloader offset 的 APP 工程
9. 带 Keil .lib 的工程
10. 带 ARMCC 专用语法的老工程
```

不同工程的处理重点不同：

```text
CubeMX 工程：
    以 .ioc 和 CubeMX 目录结构为主
    重点保护可再生成性
    不修改 Core/Drivers/Middlewares

标准库工程：
    以 .uvprojx 和源码扫描为主
    重点补齐 include / define / source / startup / linker

RTOS 工程：
    重点检查 port.c、heap_x.c、中断函数、FreeRTOSConfig.h

带 .lib 工程：
    重点判断库文件是否能被 GCC/ArmClang 使用
```

---

### 4.3 需求三：支持多编译器后端

KeilBridge 不应该只支持 GCC。

推荐三类 backend：

```text
1. GCC backend
2. ArmClang backend
3. Keil backend / fallback
```

#### GCC backend

特点：

```text
工具链：
    arm-none-eabi-gcc
    arm-none-eabi-g++
    arm-none-eabi-ld/gcc
    arm-none-eabi-objcopy
    arm-none-eabi-gdb

链接脚本：
    .ld

优点：
    开源
    跨平台
    CI 友好
    Linux 友好
    自动化生态成熟

缺点：
    ARMCC 专用语法不兼容
    Keil .lib 通常不能直接链接
    scatter 文件需要转换成 linker script
```

#### ArmClang backend

特点：

```text
工具链：
    armclang
    armlink
    armar
    fromelf

链接脚本：
    .sct scatter file

优点：
    更接近 Keil Arm Compiler 6
    对原 Keil 工程兼容性更好
    可以保留 .sct
    对部分 ARMCC/ArmClang 工程迁移成本更低

缺点：
    工具链授权和安装依赖
    CMake 配置比 GCC 复杂
    仍然需要处理部分 ARMCC5 老语法和二进制库兼容
```

#### Keil backend / fallback

特点：

```text
CMake 或脚本只是调用 Keil 命令行编译。
```

作用：

```text
1. 保留极难迁移工程的构建能力
2. 给闭源 .lib 工程提供退路
3. 用于对比 GCC/ArmClang 生成结果
```

---

### 4.4 需求四：统一调试后端

这是整个技术路线最重要的部分。

调试后端应该和编译器后端解耦：

```text
Compiler Backend:
    gcc
    armclang
    keil

Debug Backend:
    openocd_gdb
    jlink_gdb
    pyocd_gdb
```

只要最终能生成带符号的 ELF/AXF，并且调试器能通过 GDB Server 连接目标芯片，就可以自动化断点调试。

也就是说：

```text
GCC + OpenOCD + GDB        可行
GCC + J-Link GDB Server    可行
ArmClang + OpenOCD + GDB   可行
ArmClang + J-Link GDB      可行
Keil IDE GUI Debug         不推荐作为 AI 自动化路线
```

核心结论：

```text
AI 自动化调试的关键不是编译器；
关键是把 Keil GUI 调试迁移到 GDB Server + GDB 脚本 / GDB-MI。
```

---

## 5. 为什么 Keil Debug 不适合 AI 自动化

Keil Debug 的优势：

```text
1. 人工查看 Watch 方便
2. Memory/Register/Call Stack 窗口直观
3. 和 Keil 工程集成紧密
4. 对手动调试友好
```

但问题是：

```text
1. GUI 状态不适合被 AI 稳定读写
2. 断点、变量、内存、寄存器难以结构化输出
3. 难以批量自动执行测试流程
4. 难以集成到 CI/CD
5. 难以生成标准 JSON 报告
6. 不利于远程测试台和自动化 Agent
```

而 GDB 方式天然适合自动化：

```gdb
break main
continue
print g_motor.speed
x/32wx 0x20000000
info registers
bt
monitor reset halt
```

因此，KeilBridge 的调试方向应该是：

```text
给人用：
    VS Code + Cortex-Debug

给 AI 用：
    KeilBridge CLI/API + GDB-MI + JSON 输出
```

---

## 6. 总体技术架构

推荐架构：

```text
AI / Agent / MCP / 本地脚本
  ↓
KeilBridge CLI / API
  ↓
Project Scanner
  ↓
IR Builder
  ↓
Doctor Engine
  ↓
Backend Selector
  ├─ GCC backend
  ├─ ArmClang backend
  └─ Keil backend
  ↓
Build Runner
  ↓
Flash Runner
  ├─ OpenOCD
  ├─ J-Link
  └─ pyOCD
  ↓
Debug Controller
  ├─ GDB script
  ├─ GDB-MI
  └─ fault dump
  ↓
Report Generator
  ├─ JSON
  ├─ Markdown
  └─ CSV / log
```

系统模块：

```text
KeilBridge
├─ ProjectScanner
├─ IR Builder
├─ Device Database
├─ Adapter Registry
│  ├─ STM32CubeMXAdapter
│  ├─ STM32StdPeriphAdapter
│  ├─ GD32StdPeriphAdapter
│  ├─ FreeRTOSAdapter
│  ├─ RTThreadAdapter
│  └─ GenericKeilAdapter
├─ Backend Selector
│  ├─ GCC backend
│  ├─ ArmClang backend
│  └─ Keil backend
├─ Doctor Engine
│  ├─ scan doctor
│  ├─ cmake doctor
│  ├─ build doctor
│  ├─ elf doctor
│  ├─ flash doctor
│  ├─ debug doctor
│  ├─ compat doctor
│  └─ lib doctor
├─ Compat Engine
├─ Lib Resolver
├─ Debug Controller
├─ Test Runner
└─ Report Generator
```

---

## 7. 工程中间模型 IR

不要直接：

```text
.uvprojx → CMakeLists.txt
```

应该：

```text
.uvprojx / .uvoptx / .sct / .ioc / Pack / 源码扫描
    ↓
project_ir.json
    ↓
CMake / linker / startup / debug config / report
```

推荐 `project_ir.json` 包含：

```json
{
  "project": "Sentry_gimbal",
  "target": "Debug",
  "device": {
    "vendor": "ST",
    "part": "STM32F405RGTx",
    "core": "cortex-m4",
    "fpu": "fpv4-sp-d16",
    "float_abi": "hard"
  },
  "memory": {
    "flash_origin": "0x08000000",
    "flash_size": "1024K",
    "ram_origin": "0x20000000",
    "ram_size": "128K"
  },
  "framework": {
    "type": "cubemx_hal",
    "uses_hal": true,
    "uses_stdperiph": false,
    "uses_rtos": true,
    "rtos": "freertos"
  },
  "sources": [],
  "includes": [],
  "defines": [],
  "libraries": [],
  "startup": {},
  "linker": {},
  "debug": {}
}
```

IR 的意义：

```text
1. 统一不同工程类型
2. 解耦解析器和生成器
3. 方便做 Doctor 诊断
4. 方便多后端生成
5. 方便 AI 读取和分析
```

---

## 8. Device Database 设计

通用性的核心不是 CMake，而是芯片数据库。

每个芯片至少要知道：

```text
1. 厂商
2. 系列
3. 具体型号
4. Cortex 内核
5. FPU 类型
6. float ABI 推荐
7. Flash 起始地址和大小
8. RAM 起始地址和大小
9. 是否有 CCMRAM / DTCM / SRAM2
10. device macro
11. device header
12. system_xxx.c
13. startup 文件候选
14. SVD 文件
15. OpenOCD target cfg
16. J-Link device name
17. flash algorithm 风险
```

信息来源优先级：

```text
1. CMSIS-Pack / .pdsc
2. CubeMX .ioc
3. Keil .uvprojx
4. startup 文件名
5. device header
6. scatter 文件
7. 用户 board.override.yaml
```

---

## 9. board.override.yaml

自动识别永远不可能 100% 准确，因此必须允许用户覆盖。

示例：

```yaml
device:
  vendor: ST
  part: STM32F405RGTx
  core: cortex-m4
  fpu: fpv4-sp-d16
  float_abi: hard

memory:
  flash_origin: 0x08000000
  flash_size: 1024K
  ram_origin: 0x20000000
  ram_size: 128K
  ccmram_origin: 0x10000000
  ccmram_size: 64K

defines:
  add:
    - STM32F405xx
    - USE_HAL_DRIVER
  remove:
    - STM32F407xx

startup:
  prefer: startup_stm32f405xx_gcc.s

linker:
  app_flash_origin: 0x08000000
  vector_table_origin: 0x08000000

debug:
  probe: jlink
  interface: swd
  speed: 4000
  openocd_target: target/stm32f4x.cfg
  jlink_device: STM32F405RG
```

设计原则：

```text
自动识别负责给默认值；
override 负责修正不确定项。
```

---

## 10. Doctor 系统

Doctor 是提高通用性的关键。

不应该让用户直接面对 GCC 原始报错，而应该输出：

```text
为什么失败？
失败在哪一层？
能不能自动修？
能不能生成 patch？
需不需要用户确认？
是不是 GCC 后端硬边界？
是否建议换 ArmClang backend？
```

Doctor 分层：

```text
scan doctor
    检查工程识别是否可靠

cmake doctor
    检查 CMake 生成是否完整

build doctor
    解析 GCC/ArmClang 编译错误

elf doctor
    检查 ELF、段地址、向量表、符号

flash doctor
    检查烧录器、OpenOCD/J-Link、目标芯片连接

debug doctor
    检查 reset halt 后 PC/MSP/向量表/lockup

compat doctor
    检查 ARMCC 专用语法

lib doctor
    检查 .lib/.a/.o 兼容性
```

---

## 11. ELF Doctor 关键检查

很多工程“编译通过但跑不起来”，根源在 ELF。

必须检查：

```text
1. .isr_vector 是否存在
2. .isr_vector 是否位于 FLASH ORIGIN
3. Reset_Handler 是否存在
4. main 是否存在
5. _estack 是否存在
6. _estack 是否落在 RAM 范围
7. .text 是否在 Flash
8. .data / .bss 是否在 RAM
9. Flash/RAM 是否溢出
10. 是否存在 bootloader offset
11. 是否错误链接到 0x00000000
12. 是否把代码错误放进 RAM
```

正常向量表：

```text
0x08000000: 0x20020000 0x080001ed
```

异常情况：

```text
MSP = 0xFFFFFFFC
PC  = 0xFFFFFFFE
```

通常意味着：

```text
1. 程序没有真正烧进 Flash
2. .isr_vector 不在启动地址
3. linker FLASH ORIGIN 错误
4. bootloader offset 未配置
5. startup 文件符号错误
```

---

## 12. Debug Doctor 设计

Debug Doctor 不应该一上来就运行到 main，而应该先做健康检查：

```text
1. connect
2. halt
3. reset halt
4. read vector table
5. read registers
6. validate MSP/PC
7. set breakpoint main
8. continue
9. wait breakpoint
10. read variables/registers/backtrace
```

GDB 命令示例：

```gdb
target extended-remote localhost:3333
monitor reset halt
monitor mdw 0x08000000 8
info registers
break main
continue
```

如果向量表无效，应立即停止并输出：

```text
[FAIL] Reset vector invalid. Debug session aborted before run.

Diagnosis:
    Flash seems empty or application is linked to a different address.

Next:
    1. Run keilbridge flash --verify
    2. Check linker FLASH ORIGIN
    3. If bootloader exists, set linker.app_flash_origin
```

---

## 13. ARMCC 兼容策略

ARMCC 能编译但 GCC 编不过的情况很多。

常见特性：

```c
__asm
__irq
__weak
__packed
__align(4)
__forceinline
#pragma arm section
#pragma import(__use_no_semihosting)
Image$$ER_IROM1$$Base
__attribute__((at(0x20000000)))
```

处理策略分三级：

```text
Level 1：兼容头文件解决
Level 2：生成 patch，用户确认后应用
Level 3：必须人工处理
```

生成：

```text
.keilbridge/generated/compat/keil_compat.h
.keilbridge/patches/armcc_to_gcc.patch
.keilbridge/report/compat_report.md
```

`keil_compat.h` 示例：

```c
#ifndef KEIL_COMPAT_H
#define KEIL_COMPAT_H

#if defined(__GNUC__) && !defined(__CC_ARM) && !defined(__ARMCC_VERSION)

#ifndef __weak
#define __weak __attribute__((weak))
#endif

#ifndef __packed
#define __packed __attribute__((packed))
#endif

#ifndef __align
#define __align(n) __attribute__((aligned(n)))
#endif

#ifndef __forceinline
#define __forceinline inline __attribute__((always_inline))
#endif

#ifndef __STATIC_INLINE
#define __STATIC_INLINE static inline
#endif

#ifndef __ASM
#define __ASM __asm
#endif

#ifndef __INLINE
#define __INLINE inline
#endif

#endif

#endif
```

CMake 注入：

```cmake
target_compile_options(app PRIVATE
    -include ${CMAKE_SOURCE_DIR}/.keilbridge/generated/compat/keil_compat.h
)
```

---

## 14. .lib 处理策略

`.lib` 是 GCC 后端的硬边界之一。

分类：

```text
1. GCC .a 静态库
2. ARMCC5 .lib
3. ArmClang .lib
4. 厂商闭源库
5. C++ 静态库
```

处理优先级：

```text
1. 如果有源码，优先源码重编译
2. 如果有 GCC .a，替换为 GCC .a
3. 如果只有 Keil .lib，GCC backend 标记 blocked
4. 尝试推荐 ArmClang backend
5. 仍不行则保留 Keil backend
```

输出示例：

```text
[BLOCKED] Keil/ARMCC library cannot be linked by GCC.

Library:
    DJI_Motor.lib

Reason:
    ARMCC binary library is not ABI-compatible with arm-none-eabi-gcc.

Options:
    1. Ask vendor for GCC .a version
    2. Get source code and rebuild
    3. Use ArmClang backend
    4. Keep Keil backend
```

---

## 15. AI 自动化调试接口

KeilBridge 应该给 AI 暴露稳定接口，而不是让 AI 操作 IDE。

推荐命令：

```bash
keilbridge build --backend gcc --target Debug
keilbridge build --backend armclang --target Debug

keilbridge flash --probe jlink
keilbridge flash --probe openocd

keilbridge debug reset-halt
keilbridge debug check-vector
keilbridge debug break main
keilbridge debug continue
keilbridge debug read-var g_motor.speed
keilbridge debug read-mem 0x20000000 --words 32
keilbridge debug regs
keilbridge debug bt
keilbridge debug fault-dump
keilbridge debug smoke-test
```

AI 工具接口：

```json
{
  "tool": "debug_smoke_test",
  "args": {
    "elf": ".keilbridge/build/gcc-debug/app.elf",
    "probe": "jlink",
    "device": "STM32F405RG"
  }
}
```

输出：

```json
{
  "status": "pass",
  "hit_breakpoint": "main",
  "pc": "0x080092a4",
  "msp": "0x2001fff0",
  "xpsr": "0x01000000",
  "variables": {
    "g_system_state": 1
  }
}
```

---

## 16. 自动化调试最小闭环

最小闭环：

```text
1. build
2. flash
3. reset halt
4. check vector table
5. break main
6. continue
7. wait until main hit
8. read registers
9. read selected variables
10. export debug_result.json
```

`debug.yaml` 示例：

```yaml
probe:
  type: jlink
  device: STM32F405RG
  interface: swd
  speed: 4000

elf: .keilbridge/build/gcc-debug/app.elf

actions:
  - reset_halt
  - check_vector_table
  - break: main
  - continue
  - wait_breakpoint: main
  - read_registers
  - read_variable: g_system_state
  - read_memory:
      address: 0x20000000
      words: 16

output:
  json: .keilbridge/report/debug_result.json
```

---

## 17. 自动化断点能力

应支持：

```text
1. 函数断点
2. 文件行号断点
3. 条件断点
4. Watchpoint
5. HardFault 自动断点
6. 断点命中后读取变量
7. 断点命中后 dump 寄存器和栈
8. 超时未命中断点自动失败
```

示例：

```gdb
break main
break HardFault_Handler
break Service_Device.cpp:137
break motor_control.c:188 if speed_fbk > 1000
watch fault_code
```

配置化表达：

```yaml
actions:
  - break: main
  - break: HardFault_Handler
  - break:
      location: motor_control.c:188
      condition: speed_fbk > 1000
  - watch: fault_code
  - continue
  - wait_any:
      - main
      - HardFault_Handler
```

---

## 18. AI 自动化测试闭环

KeilBridge 不只是编译调试工具，还应该是测试闭环入口。

推荐流程：

```text
AI
  ↓
读取 test.yaml
  ↓
调用 keilbridge build
  ↓
调用 keilbridge flash
  ↓
调用 keilbridge debug smoke-test
  ↓
调用串口/RTT/SWO 测试脚本
  ↓
采集 CSV/log
  ↓
分析结果
  ↓
生成 report.md/result.json
  ↓
AI 判断下一步
```

测试用例示例：

```yaml
test_name: motor_speed_loop_basic_test

build:
  backend: gcc
  target: Debug

flash:
  probe: jlink
  device: STM32F405RG

debug:
  smoke_test: true
  breakpoints:
    - main
    - HardFault_Handler
  read_variables:
    - g_system_state
    - g_fault_code

runtime:
  transport: uart
  port: COM8
  baudrate: 921600
  command:
    - motor_enable
    - run_speed_test

analysis:
  output_json: report/result.json
  output_md: report/result.md
```

---

## 19. 路线选择总结

### 19.1 GCC + CMake

适合：

```text
1. 新工程
2. 无闭源 Keil .lib
3. ARMCC 专用语法较少
4. 目标是 Linux/CI/开源工具链
5. 希望彻底摆脱 Keil 编译器生态
```

### 19.2 ArmClang + CMake

适合：

```text
1. 老 Keil 工程
2. 有复杂 .sct
3. 有较多 ARMCC/ArmClang 习惯
4. 有部分 Keil/Arm 库依赖
5. 想先脱离 Keil IDE，但不急着换 GCC
```

### 19.3 Keil backend

适合：

```text
1. 有无法替换的闭源 .lib
2. 有大量无法迁移的 ARMCC5 专用代码
3. 短期只想把 Keil 构建纳入自动化流程
4. 用于对比原始 Keil 构建结果
```

### 19.4 统一调试后端

最终无论编译器怎么选，都应该尽量走：

```text
ELF/AXF + GDB Server + GDB/GDB-MI + JSON 报告
```

---

## 20. 分阶段落地路线

### 阶段 1：统一 IR 和基础 CMake 生成

目标：

```text
把 .uvprojx 解析成 project_ir.json。
```

完成：

```text
1. 解析 sources
2. 解析 includes
3. 解析 defines
4. 解析 target
5. 解析 device
6. 生成 GCC CMake
7. 生成基础 report
```

---

### 阶段 2：Build Doctor

目标：

```text
让工具能解释编译失败原因。
```

完成：

```text
1. include 缺失诊断
2. 宏缺失诊断
3. startup 错误诊断
4. system_xxx.c 缺失诊断
5. HAL/SPL 源文件缺失诊断
6. RTOS port 错误诊断
7. .lib 不兼容诊断
```

---

### 阶段 3：ELF Doctor

目标：

```text
提前发现“编译过了但不能跑”的问题。
```

完成：

```text
1. 检查 .isr_vector
2. 检查 Reset_Handler
3. 检查 _estack
4. 检查 main
5. 检查段地址
6. 检查 Flash/RAM 占用
7. 检查 bootloader offset
```

---

### 阶段 4：Debug Doctor

目标：

```text
调试前先确认芯片能正常 reset/halt/读向量表。
```

完成：

```text
1. OpenOCD/J-Link 配置检查
2. reset halt
3. read vector table
4. validate MSP/PC
5. break main
6. fault dump
7. debug_result.json
```

---

### 阶段 5：Compat Doctor

目标：

```text
处理 ARMCC → GCC/ArmClang 的代码兼容问题。
```

完成：

```text
1. 扫描 __asm
2. 扫描 __weak / __packed / __align
3. 扫描 pragma
4. 扫描 Image$$ 符号
5. 生成 keil_compat.h
6. 生成 patch
7. 生成 compat_report.md
```

---

### 阶段 6：Lib Doctor

目标：

```text
把 .lib 问题从“编译失败”升级为“后端兼容性诊断”。
```

完成：

```text
1. 扫描 .lib/.a/.o
2. 判断 GCC 是否可读
3. 查找源码替代
4. 查找 GCC .a
5. 推荐 backend
6. 生成 lib_report.md
```

---

### 阶段 7：ArmClang backend

目标：

```text
提高老 Keil 工程和带 .lib 工程的迁移成功率。
```

完成：

```text
1. armclang toolchain file
2. armlink 参数生成
3. 复用 .sct
4. fromelf 生成 hex/bin
5. ArmClang build doctor
6. ArmClang + GDB debug 流程验证
```

---

### 阶段 8：AI 自动化测试接口

目标：

```text
让 AI 可以调用 KeilBridge 完成构建、下载、断点、变量读取、测试分析。
```

完成：

```text
1. CLI JSON 输出
2. MCP 工具封装
3. build_firmware
4. flash_firmware
5. debug_smoke_test
6. read_variable
7. fault_dump
8. run_test
9. analyze_result
10. generate_report
```

---

## 21. 最终技术路线图

最终推荐路线：

```text
Keil 工程
  ↓
非侵入式扫描
  ↓
project_ir.json
  ↓
Doctor 诊断
  ↓
backend 推荐
  ├─ GCC backend
  ├─ ArmClang backend
  └─ Keil fallback
  ↓
CMake 构建
  ↓
生成 ELF/HEX/BIN/MAP
  ↓
Flash backend
  ├─ OpenOCD
  ├─ J-Link
  └─ pyOCD
  ↓
GDB Debug backend
  ↓
Debug Doctor
  ↓
自动断点 / 变量 / 内存 / 寄存器 / fault dump
  ↓
JSON / Markdown 报告
  ↓
AI 分析和下一步决策
```

---

## 22. 关键结论

### 22.1 编译器不是最终目的

```text
GCC 不是目的；
ArmClang 也不是目的；
Keil 也不是必须完全抛弃。

真正的目的是：
    让编译、下载、调试、测试可以自动化、脚本化、结构化、AI 可调用。
```

### 22.2 编译后端和调试后端必须解耦

```text
Compiler Backend:
    决定怎么生成 ELF

Debug Backend:
    决定怎么连接芯片、打断点、读变量
```

只要能生成带符号的 ELF，并能被 GDB Server 调试，就可以进入 AI 自动化链路。

### 22.3 KeilBridge 应该优雅降级

```text
能 GCC 就 GCC；
GCC 不适合就 ArmClang；
ArmClang 也不适合就 Keil fallback；
所有失败都输出 Doctor 诊断。
```

### 22.4 AI 需要的是结构化接口

AI 不应该操作 Keil GUI。

AI 应该调用：

```text
build()
flash()
debug_smoke_test()
set_breakpoint()
read_variable()
fault_dump()
run_test()
analyze_result()
```

并读取：

```text
doctor_result.json
build_result.json
debug_result.json
test_result.json
```

---

## 23. 最终一句话总结

```text
KeilBridge 的最终形态不是“Keil 转 GCC 小工具”，
而是一个面向嵌入式工程的非侵入式迁移、构建、下载、调试、诊断和 AI 自动化测试平台。

它通过 CMake 解耦工程构建，
通过 GCC/ArmClang/Keil 多后端提高兼容性，
通过 GDB Server/GDB-MI 替代 Keil GUI 调试，
通过 Doctor 系统定位迁移失败原因，
通过 JSON/Markdown 报告让 AI 能稳定参与自动化调试闭环。
```
