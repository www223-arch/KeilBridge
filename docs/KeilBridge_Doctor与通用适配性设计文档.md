# KeilBridge Doctor 与通用适配性设计文档

> 主题：面向“0 侵入式 Keil → CMake/GCC 转换工具”的通用适配、诊断、ARMCC 兼容与 `.lib` 处理策略  
> 适用对象：KeilBridge / Keil2CMake / Keil 工程迁移工具开发  
> 目标：让工具不仅能“转换成功”，更能在失败时给出结构化诊断、兼容补丁和替代路线。

---

## 1. 背景与核心问题

目前工具已经能够跑通部分 GD 裸机和 RTOS 工程，但换成 STM32、同厂商不同型号、CubeMX 工程、标准库工程、RTOS 工程或带 `.lib` 的工程后，容易出现不兼容。

常见问题包括：

```text
1. 芯片型号识别不准
2. core / fpu / float-abi 判断错误
3. Flash / RAM 地址不准
4. startup 文件选错
5. linker script 生成错误
6. Keil 宏定义没有完整迁移
7. include path 漏掉
8. RTOS port 没有从 RVDS/ARMCC 切换到 GCC
9. ARMCC 专用语法导致 GCC 编译失败
10. Keil .lib 不能被 GCC 链接
11. OpenOCD / J-Link device 名称不匹配
12. 有 bootloader offset，但工具按 0x08000000 处理
13. GCC 编译通过，但 ELF 向量表错误，程序复位后 lockup
```

因此，KeilBridge 不应该只是一个“CMake 生成器”，而应该是：

```text
非侵入式 Keil 工程迁移与诊断工具
```

核心原则：

```text
不要让用户面对 GCC 原始报错；
让用户面对 KeilBridge 的诊断结论。
```

---

## 2. 产品定位

不建议把工具定位成：

```text
任何 Keil 工程都 0 成本转 GCC
```

这个目标不现实，因为存在 ARMCC 专用语法、闭源 `.lib`、编译器 ABI 差异、启动文件语法差异、RTOS port 差异、bootloader 偏移等硬边界。

更合理的定位是：

```text
KeilBridge 是一个非侵入式 Keil 工程迁移与诊断工具。
它会尽量自动生成 CMake/GCC 构建；
对于无法自动迁移的部分，输出结构化诊断、兼容补丁和替代后端建议。
```

具体策略：

```text
能自动转的，自动转。
能兼容头解决的，生成 compat。
能 patch 的，生成 patch。
能换源码的，换源码。
只能换 GCC .a 的，提示找库。
必须保留 Keil/ArmClang 的，明确告诉用户。
```

---

## 3. 0 侵入式原则

0 侵入式不是“无脑修改原工程”，而是：

```text
1. 不修改原 .c / .h / .s 源码
2. 不修改原 .uvprojx / .uvoptx
3. 不破坏 Keil 原工程
4. 不移动用户目录结构
5. 所有生成文件放到 .keilbridge/ 或 generated/ 下
6. 所有补丁以 patch/report 形式输出，由用户确认是否应用
7. 所有自动判断都允许 board.override.yaml 覆盖
```

推荐输出结构：

```text
.keilbridge/
├─ generated/
│  ├─ CMakeLists.txt
│  ├─ cmake/
│  │  ├─ arm-none-eabi-gcc.cmake
│  │  ├─ mcu_flags.cmake
│  │  ├─ sources.cmake
│  │  └─ flash.cmake
│  ├─ linker/
│  │  └─ device.ld
│  ├─ startup/
│  │  └─ startup_device_gcc.s
│  ├─ compat/
│  │  └─ keil_compat.h
│  ├─ openocd/
│  │  └─ target.cfg
│  ├─ jlink/
│  │  └─ flash.jlink
│  └─ vscode/
│     ├─ launch.json
│     ├─ tasks.json
│     └─ settings.json
│
├─ build/
│
├─ report/
│  ├─ doctor_report.md
│  ├─ doctor_result.json
│  ├─ compat_report.md
│  ├─ lib_report.md
│  └─ project_ir.json
│
└─ patches/
   └─ armcc_to_gcc.patch
```

---

## 4. Doctor 系统总体设计

建议把 `debug doctor` 扩展为完整的 **KeilBridge Doctor 系统**。

整体流程：

```text
Keil 工程
  ↓
scan doctor        检查工程识别是否可靠
  ↓
cmake doctor       检查生成的 CMake 是否完整
  ↓
build doctor       检查 GCC 编译错误并分类
  ↓
elf doctor         检查 ELF、段地址、符号、向量表
  ↓
flash doctor       检查烧录配置、调试器、OpenOCD/J-Link
  ↓
debug doctor       检查复位后 PC/MSP/VTOR/HardFault/lockup
  ↓
compat doctor      检查 ARMCC 专用语法
  ↓
lib doctor         检查 Keil .lib / GCC .a / ABI 兼容性
```

建议命令：

```bash
keilbridge doctor scan   path/to/project.uvprojx --target Debug
keilbridge doctor cmake  path/to/project.uvprojx --target Debug
keilbridge doctor build  path/to/project.uvprojx --target Debug
keilbridge doctor elf    path/to/project.uvprojx --target Debug
keilbridge doctor flash  path/to/project.uvprojx --target Debug
keilbridge doctor debug  path/to/project.uvprojx --target Debug
keilbridge doctor compat path/to/project.uvprojx --target Debug
keilbridge doctor lib    path/to/project.uvprojx --target Debug
keilbridge doctor all    path/to/project.uvprojx --target Debug
```

---

## 5. Doctor 结果格式设计

每个检查项都应该是结构化结果，而不是简单打印字符串。

推荐 JSON 格式：

```json
{
  "id": "ELF_VECTOR_INVALID",
  "stage": "elf",
  "severity": "fatal",
  "title": "中断向量表无效",
  "message": "检测到 .isr_vector 不在 FLASH 起始地址，复位后可能无法进入 Reset_Handler。",
  "evidence": {
    "flash_origin": "0x08000000",
    "isr_vector_addr": "0x08004000",
    "reset_handler": "0x080041ed"
  },
  "possible_causes": [
    "工程存在 bootloader offset，但工具未识别",
    "linker script FLASH ORIGIN 错误",
    ".isr_vector 被链接到错误地址"
  ],
  "auto_fix": {
    "available": true,
    "action": "generate_linker_with_flash_origin",
    "requires_confirm": true
  },
  "manual_fix": [
    "确认 APP 是否从 0x08000000 启动",
    "如果有 bootloader，请在 board.override.yaml 配置 app_flash_origin"
  ]
}
```

严重程度建议：

```text
info      信息
pass      通过
warn      有风险但不一定失败
fail      当前阶段失败
fatal     阻塞后续流程
manual    必须人工处理
blocked   当前后端无法支持
```

---

## 6. Scan Doctor：工程识别诊断

### 6.1 目标

解决“换芯片就不行”的问题。

Scan Doctor 要把工程中的各种信息统一提取为 `project_ir.json` 和 `device_ir`。

推荐 `device_ir`：

```json
{
  "vendor": "ST",
  "series": "STM32F4",
  "part": "STM32F405RGTx",
  "core": "cortex-m4",
  "fpu": "fpv4-sp-d16",
  "float_abi": "hard",
  "flash": {
    "origin": "0x08000000",
    "size": "1024K"
  },
  "ram": [
    {
      "name": "RAM",
      "origin": "0x20000000",
      "size": "128K"
    },
    {
      "name": "CCMRAM",
      "origin": "0x10000000",
      "size": "64K"
    }
  ],
  "startup_candidates": [
    "startup_stm32f405xx.s",
    "startup_stm32f40_41xxx.s"
  ],
  "system_file": "system_stm32f4xx.c",
  "device_header": "stm32f405xx.h",
  "defines": [
    "STM32F405xx",
    "USE_HAL_DRIVER"
  ],
  "openocd_target": "target/stm32f4x.cfg",
  "jlink_device": "STM32F405RG"
}
```

### 6.2 检查内容

```text
1. 从 .uvprojx 识别 device 名称
2. 从 .uvoptx 识别调试配置
3. 从源码 include 识别 device header
4. 从宏定义识别芯片系列
5. 从 startup 文件名识别芯片系列
6. 从 scatter 文件识别 Flash/RAM 布局
7. 从 .ioc 识别 CubeMX 芯片信息
8. 从 Pack/.pdsc 识别内核、内存、启动文件
9. 多个来源冲突时给出置信度
```

### 6.3 置信度机制

示例：

```json
{
  "device_candidates": [
    {
      "part": "STM32F405RGTx",
      "confidence": 0.86,
      "evidence": [
        "uvprojx device name",
        "startup_stm32f405xx.s",
        "stm32f4xx_hal_conf.h",
        "scatter flash size 1024K"
      ]
    },
    {
      "part": "STM32F407VGTx",
      "confidence": 0.41,
      "evidence": [
        "STM32F407xx define found in old header"
      ]
    }
  ]
}
```

如果置信度低于阈值：

```text
[ASK_OVERRIDE] Device detection confidence too low.
Please confirm device.part in board.override.yaml.
```

---

## 7. board.override.yaml：用户覆盖机制

自动识别不可能 100% 准确，必须允许用户覆盖。

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
  probe: cmsis-dap
  server: openocd
  openocd_target: target/stm32f4x.cfg
  jlink_device: STM32F405RG
```

Doctor 发现不确定时，应该生成 override 模板，而不是中断流程：

```text
.keilbridge/generated/board.override.template.yaml
```

---

## 8. CMake Doctor：CMake 生成结果检查

CMake Doctor 不执行编译，只检查生成的 CMake 是否完整。

### 8.1 检查项

```text
1. 是否存在 toolchain file
2. 是否设置 CMAKE_SYSTEM_NAME Generic
3. 是否设置 arm-none-eabi-gcc/g++/gcc 作为 ASM 编译器
4. target_sources 是否包含 startup
5. target_sources 是否包含 system_xxx.c
6. include 是否包含 CMSIS/Core
7. include 是否包含 CMSIS/Device
8. include 是否包含 HAL/SPL/GD 标准库 include
9. defines 是否包含芯片宏
10. defines 是否包含 USE_HAL_DRIVER / USE_STDPERIPH_DRIVER
11. link_options 是否包含 -T linker.ld
12. 是否生成 .elf/.hex/.bin/.map
13. 是否 Debug 使用 -g3 -Og
14. 是否 Release 使用合适优化等级
```

### 8.2 示例输出

```text
[OK] Toolchain: arm-none-eabi-gcc
[OK] MCU flags: -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
[OK] Startup file included
[OK] System file included: system_stm32f4xx.c
[FAIL] Missing define: STM32F405xx
[WARN] USE_HAL_DRIVER detected in source but not added to CMake definitions
[WARN] FreeRTOS detected, but GCC ARM_CM4F port.c was not selected
```

---

## 9. Build Doctor：GCC 编译错误分类

Build Doctor 的目标不是原样转发 GCC 错误，而是将错误转换成用户能理解的迁移诊断。

### 9.1 常见错误分类

```text
fatal error: xxx.h no such file
    → include path 缺失 / 库组件未加入

unknown type name IRQn_Type
    → CMSIS 设备头文件不匹配 / 芯片宏漏了 / include 顺序错误

bad instruction / unknown pseudo-op / AREA / EXPORT / DCD
    → Keil ARMASM 启动文件被 GCC 编译了

undefined reference to Reset_Handler
    → startup 没加入 / ENTRY 不一致

undefined reference to SystemInit
    → system_xxx.c 没加入

undefined reference to HAL_xxx
    → HAL 源文件没加入

multiple definition of xxx
    → 重复加入源码 / RTOS heap 多选

uses VFP register arguments
    → FPU ABI 不一致

file format not recognized: xxx.lib
    → Keil .lib 不能给 GCC 链接
```

### 9.2 规则库示例

```yaml
- id: MISSING_INCLUDE
  regex: "fatal error: (.*): No such file or directory"
  stage: compile
  severity: fatal
  cause: "include path missing or component source missing"
  suggestion: "检查 Keil Include Paths 是否完整迁移"

- id: IRQN_TYPE_UNKNOWN
  regex: "unknown type name 'IRQn_Type'"
  stage: compile
  severity: fatal
  cause: "CMSIS device header or chip macro mismatch"
  suggestion: "检查 device macro、CMSIS include order、core_cmxx.h 是否混用"

- id: ARMASM_DIALECT
  regex: "bad instruction|unknown pseudo-op|AREA|EXPORT|DCD"
  stage: assemble
  severity: fatal
  cause: "Keil ARMASM startup was passed to GCC assembler"
  suggestion: "替换为 GNU as startup_xxx_gcc.s"

- id: FLOAT_ABI_MISMATCH
  regex: "uses VFP register arguments|does not use VFP register arguments"
  stage: link
  severity: fatal
  cause: "hard-float/soft-float ABI mismatch"
  suggestion: "统一 -mfloat-abi 和第三方库 ABI"

- id: ARMCC_LIB_INCOMPATIBLE
  regex: "file format not recognized|archive has no index|cannot find"
  stage: link
  severity: fatal
  cause: "Keil/ARMCC .lib cannot be linked by GCC"
  suggestion: "寻找 GCC .a 版本或源码重编译"
```

---

## 10. ELF Doctor：链接产物健康检查

GCC 编译链接成功，不代表程序能跑。

ELF Doctor 要用以下工具检查产物：

```text
arm-none-eabi-objdump -h
arm-none-eabi-nm -n
arm-none-eabi-readelf -S
arm-none-eabi-size
```

### 10.1 检查项

```text
1. .isr_vector 是否存在
2. .isr_vector 是否位于 FLASH ORIGIN
3. Reset_Handler 是否存在
4. main 是否存在
5. _estack 是否存在
6. _estack 是否落在 RAM 范围内
7. .text 是否在 Flash
8. .data/.bss 是否在 RAM
9. .data LMA 是否在 Flash
10. 是否生成 .map
11. Flash/RAM 占用是否超过容量
12. 是否有异常段被放到 0x00000000
13. 是否错误把代码链接到 RAM
14. 是否缺失 KEEP(*(.isr_vector))
```

### 10.2 向量表检查

正常 Cortex-M 向量表前两个 word 应该类似：

```text
0x08000000: 0x20020000 0x080001ed
```

其中：

```text
第一个 word：初始 MSP，应该落在 RAM 范围
第二个 word：Reset_Handler，应该落在 Flash 范围，且最低位为 1
```

异常情况：

```text
MSP = 0xFFFFFFFC
PC  = 0xFFFFFFFE
```

通常说明：

```text
1. 程序没有真正烧进 Flash
2. .isr_vector 不在启动地址
3. linker FLASH ORIGIN 错误
4. bootloader offset 未配置
5. startup 文件符号错误
```

### 10.3 示例输出

```text
[FAIL] Vector table invalid or not programmed

Expected:
    MSP in RAM:   0x20000000 ~ 0x2001FFFF
    Reset in ROM: 0x08000000 ~ 0x080FFFFF

Observed:
    MSP = 0xFFFFFFFC
    PC  = 0xFFFFFFFE

Likely causes:
    1. Flash was not programmed
    2. .isr_vector is not located at boot address
    3. Linker FLASH ORIGIN is wrong
    4. Bootloader offset not configured
```

---

## 11. Flash Doctor：烧录链路检查

Flash Doctor 检查调试器、烧录器、OpenOCD/J-Link 配置。

### 11.1 检查项

```text
1. OpenOCD/J-Link 是否存在
2. 使用的 OpenOCD 是否适合当前芯片
3. interface cfg 是否存在
4. target cfg 是否存在
5. J-Link device name 是否匹配
6. ELF/HEX/BIN 文件是否存在
7. launch.json 是否有 program/load 动作
8. 是否能读芯片 ID
9. 是否能 halt
10. 是否能读 0x08000000 向量表
```

### 11.2 OpenOCD 版本风险

如果目标是 STM32/GD32，但使用了 ESP-IDF 自带 OpenOCD：

```text
D:/ESP32/Esp_idf/.../openocd-esp32/bin/openocd.exe
```

应输出警告：

```text
[WARN] OpenOCD serverpath points to ESP-IDF OpenOCD.
Current target: STM32F405RGTx

Suggestion:
    Use xPack OpenOCD, STM32CubeCLT OpenOCD, or system OpenOCD.
```

---

## 12. Debug Doctor：复位健康检查

Debug Doctor 不应该一上来就 `continue` 到 main，而应该先做：

```text
1. connect
2. halt
3. reset halt
4. read registers
5. read vector table
6. validate MSP/PC
7. only if valid, set breakpoint main
8. continue
```

### 12.1 GDB/OpenOCD 命令

```gdb
monitor reset halt
monitor reg
monitor mdw 0x08000000 8
```

### 12.2 检查规则

```text
MSP 必须落在 RAM 范围：
    0x20000000 ~ RAM_END

Reset_Handler 必须落在 Flash 范围：
    FLASH_ORIGIN ~ FLASH_END

Reset_Handler bit0 通常应为 1：
    Thumb 状态入口

PC 不能是：
    0x00000000
    0xFFFFFFFF
    0xFFFFFFFE

MSP 不能是：
    0x00000000
    0xFFFFFFFF
    0xFFFFFFFC
```

### 12.3 失败时不要继续调试

如果向量表检查失败，不应该继续打 main 断点。否则用户只会看到 lockup / double fault 噪声。

示例输出：

```text
[FAIL] Reset vector invalid. Debug session aborted before run.

Read from 0x08000000:
    word0 MSP: 0xFFFFFFFF
    word1 PC : 0xFFFFFFFF

Diagnosis:
    Flash seems empty or application is linked to a different address.

Next:
    1. Run: keilbridge flash --verify
    2. Check linker FLASH ORIGIN
    3. If bootloader exists, set linker.app_flash_origin
```

---

## 13. Compat Doctor：ARMCC → GCC 兼容诊断

ARMCC 能编译但 GCC 编译不过，这是 Keil 转 GCC 的常见问题。

### 13.1 常见 ARMCC/Keil 专用语法

```c
__asm
__irq
__weak
__packed
__align(4)
__forceinline
__STATIC_INLINE
__attribute__((at(0x20000000)))
#pragma arm section
#pragma import(__use_no_semihosting)
#pragma diag_suppress
__disable_fiq()
__enable_fiq()
```

Keil scatter 符号：

```c
extern unsigned int Image$$ER_IROM1$$Base;
extern unsigned int Image$$ER_IROM1$$Limit;
extern unsigned int Image$$RW_IRAM1$$Base;
extern unsigned int Image$$RW_IRAM1$$ZI$$Limit;
```

### 13.2 处理原则

不要默认修改用户源码。分三级处理：

```text
Level 1：兼容头文件修复
Level 2：生成 patch，用户确认后应用
Level 3：标记为人工处理
```

生成文件：

```text
.keilbridge/generated/compat/keil_compat.h
.keilbridge/report/compat_report.md
.keilbridge/patches/armcc_to_gcc.patch
```

### 13.3 keil_compat.h 示例

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

CMake 中自动注入：

```cmake
target_include_directories(app PRIVATE
    ${CMAKE_SOURCE_DIR}/.keilbridge/generated/compat
)

target_compile_options(app PRIVATE
    -include ${CMAKE_SOURCE_DIR}/.keilbridge/generated/compat/keil_compat.h
)
```

---

## 14. ARMCC 兼容问题分级

### 14.1 A 类：可以自动兼容

```text
__weak
__packed
__align
__forceinline
__STATIC_INLINE
```

处理方式：

```text
生成 keil_compat.h
不修改源码
```

### 14.2 B 类：可以生成 patch，但需要用户确认

例如绝对地址变量：

```c
uint8_t buffer[128] __attribute__((at(0x20001000)));
```

GCC 更推荐：

```c
__attribute__((section(".fixed_buffer"))) uint8_t buffer[128];
```

同时 linker script 添加：

```ld
.fixed_buffer 0x20001000 (NOLOAD) :
{
    KEEP(*(.fixed_buffer))
} > RAM
```

这类需要确认地址、对齐、NOLOAD、段属性，因此不建议自动改源码，只生成 patch。

### 14.3 C 类：必须人工处理

```text
1. 大段 __asm 内联汇编
2. #pragma arm section
3. Image$$ER_IROM1$$Base 等 scatter 符号
4. Keil .lib
5. C++ ABI 相关依赖
6. 编译器私有启动代码
```

输出示例：

```text
[MANUAL] Detected ARMCC inline assembly in bsp_delay.c:123

Reason:
    GCC inline assembly syntax is different.

Suggestion:
    Rewrite this function for GCC or provide compiler-specific implementation.
```

---

## 15. ARMCC 内联汇编处理建议

不要试图自动翻译所有汇编。更优雅的方式是隔离式适配：

```c
#if defined(__CC_ARM) || defined(__ARMCC_VERSION)
/* ARMCC implementation */
__asm void foo(void)
{
    ...
}
#elif defined(__GNUC__)
/* GCC implementation */
__attribute__((naked)) void foo(void)
{
    __asm volatile (
        "...\n"
    );
}
#endif
```

很多裸机工程里的 ARMCC 汇编其实只是：

```text
1. 简单延时
2. 开关中断
3. NOP
4. WFI
5. 读写 MSP/PSP
```

这些可以优先替换为 CMSIS intrinsic：

```c
__disable_irq();
__enable_irq();
__NOP();
__WFI();
__get_MSP();
__set_MSP(x);
```

Compat Doctor 应输出建议：

```text
检测到 ARMCC 汇编函数：
    file: bsp_delay.c
    function: delay_us
    line: 88

建议：
    1. 改成 CMSIS intrinsic
    2. 或提供 GCC 分支实现
    3. 或使用 DWT/SysTick 替代手写汇编延时
```

---

## 16. Lib Doctor：Keil .lib 与 GCC 兼容性

`.lib` 是 GCC 后端的硬边界之一。

### 16.1 库文件分类

扫描：

```text
*.lib
*.a
*.o
```

分类：

```text
1. GCC .a 静态库
2. ARMCC5 .lib
3. ArmClang .lib
4. 普通 COFF/ELF object
5. 厂商闭源库
6. C++ 静态库
```

可用工具：

```bash
arm-none-eabi-readelf -h libxxx.a
arm-none-eabi-nm libxxx.a
file libxxx.lib
```

如果 GCC 工具读不了，大概率不能用 GCC 链接。

---

## 17. .lib 处理策略

### 17.1 策略 1：源码重编译，最优

如果库对应源码存在：

```text
Lib/
Src/
Drivers/
Middlewares/
```

则自动改成源码编译。

输出：

```text
[FIX] Found source alternative for xxx.lib
      Removed xxx.lib
      Added 23 source files from Middleware/xxx/src
```

### 17.2 策略 2：查找 GCC 版本 .a

扫描：

```text
**/gcc/*.a
**/GCC/*.a
**/armgcc/*.a
**/*gcc*.a
```

如果找到：

```text
[AUTO] Replace ARMCC lib:
       old: Lib/xxx_keil.lib
       new: Lib/GCC/libxxx.a
```

### 17.3 策略 3：生成阻塞报告

如果只有 Keil `.lib`，没有源码，没有 GCC `.a`：

```text
[BLOCKED] Keil/ARMCC library cannot be linked by GCC.

Library:
    DJI_Motor.lib

Reason:
    ARMCC binary library is not ABI-compatible with arm-none-eabi-gcc.

Options:
    1. Ask vendor for GCC .a version
    2. Get source code and rebuild
    3. Keep this target on Keil/ArmClang backend
    4. Replace this module with open-source implementation
```

### 17.4 策略 4：多后端构建

支持：

```bash
keilbridge convert --backend gcc
keilbridge convert --backend armclang
keilbridge convert --backend keil
```

对于强依赖 `.lib` 的工程，优雅降级：

```text
该工程不适合 GCC 后端。
推荐使用 ArmClang 或保留 Keil 后端。
```

### 17.5 策略 5：CMake 调用 Keil 构建

最保守方案：

```cmake
add_custom_target(keil_build
    COMMAND UV4.exe -b Project.uvprojx -t TargetName
)
```

这不是最终目标，但对闭源库工程可以保持原工作流不中断。

---

## 18. Lib Doctor 输出示例

```text
[FAIL] ARMCC library detected: Lib/DJI_Motor.lib

Compatibility:
    GCC backend:      unsupported
    ArmClang backend: maybe
    Keil backend:     supported

Recommended path:
    1. Search vendor package for GCC .a
    2. If source exists, rebuild from source
    3. If only .lib exists, use armclang backend or keep Keil build

Generated:
    .keilbridge/report/lib_report.md
```

如果是 C++ 库，要更谨慎：

```text
[FAIL] C++ prebuilt library detected.

Reason:
    C++ ABI/name mangling/exception/runtime may differ between compilers.

Suggestion:
    Rebuild with same compiler as final toolchain.
```

---

## 19. RTOS Doctor：RTOS 工程检查

RTOS 工程最容易“编译通过但运行异常”。

### 19.1 FreeRTOS 检查项

```text
1. 是否只选择了一个 heap_x.c
2. 是否选择了 GCC port.c
3. port 是否匹配 core/fpu
4. FreeRTOSConfig.h 是否在 include 中
5. SysTick_Handler / PendSV_Handler / SVC_Handler 是否冲突
6. 是否使用 CMSIS-RTOS wrapper
7. 中断优先级宏是否合理
8. configPRIO_BITS 是否匹配芯片
```

### 19.2 常见 port 迁移问题

Keil/RVDS 工程常见：

```text
portable/RVDS/ARM_CM4F/port.c
```

GCC 应替换为：

```text
portable/GCC/ARM_CM4F/port.c
```

Doctor 输出：

```text
[FAIL] FreeRTOS uses RVDS/ARMCC port in GCC backend:
       Middlewares/FreeRTOS/portable/RVDS/ARM_CM4F/port.c

Suggested replacement:
       Middlewares/FreeRTOS/portable/GCC/ARM_CM4F/port.c
```

---

## 20. 适配器架构

不要把所有逻辑写在 CMake generator 里。

推荐架构：

```text
KeilBridge
├─ ProjectScanner
├─ IR Builder
├─ Doctor Engine
├─ Adapter Registry
│  ├─ STM32CubeMXAdapter
│  ├─ STM32StdPeriphAdapter
│  ├─ GD32StdPeriphAdapter
│  ├─ FreeRTOSAdapter
│  ├─ RTThreadAdapter
│  └─ GenericKeilAdapter
├─ Device Database
│  ├─ STM32 database
│  ├─ GD32 database
│  ├─ CMSIS-Pack parser
│  └─ user override yaml
├─ Compat Engine
│  ├─ ARMCC syntax scanner
│  ├─ GCC compat header generator
│  ├─ patch generator
│  └─ manual issue reporter
├─ Lib Resolver
│  ├─ lib type detector
│  ├─ source alternative finder
│  ├─ gcc .a finder
│  └─ backend recommender
└─ Generators
   ├─ CMake generator
   ├─ linker generator
   ├─ startup selector
   ├─ vscode generator
   ├─ openocd generator
   └─ report generator
```

职责划分：

```text
工程扫描只负责发现事实
Adapter 负责解释事实
Doctor 负责检查风险
Generator 负责生成文件
Compat 负责兼容补丁
Lib Resolver 负责闭源库策略
```

不要让 CMake generator 里到处写：

```python
if "GD32" in device:
    ...
elif "STM32" in device:
    ...
```

否则后期扩展会非常困难。

---

## 21. Backend 推荐器

当扫描到库或编译器私有特性时，可以输出后端兼容矩阵：

```text
Library compatibility matrix:

Library              GCC       ArmClang    Keil
-------------------------------------------------
motor_control.lib    FAIL      MAYBE       OK
dsp_gcc.a            OK        UNKNOWN     UNKNOWN
foo_source/          OK        OK          OK
```

结论：

```text
Recommended backend:
    armclang

Reason:
    Project contains ARMCC binary libraries.
```

如果用户强制 GCC：

```bash
keilbridge convert --backend gcc --allow-incompatible-lib
```

报告中标记：

```text
[BLOCKED] Build is expected to fail due to incompatible binary libraries.
```

---

## 22. Compat 模式设计

建议提供三种模式：

```bash
keilbridge convert --compat-mode report
keilbridge convert --compat-mode header
keilbridge convert --compat-mode patch
```

含义：

```text
report：
    只报告，不改任何东西

header：
    生成 keil_compat.h，并自动 -include

patch：
    生成 patch 文件，用户确认后应用
```

默认建议：

```text
header + report
```

不要默认 patch 用户代码。

---

## 23. Doctor 汇总报告示例

```text
KeilBridge Doctor Report
Target: Sentry_gimbal
Backend: GCC
Device: STM32F405RGTx

Summary:
  PASS: 42
  WARN: 8
  FAIL: 3
  MANUAL: 2

Fatal:
  [ELF_VECTOR_INVALID] Reset vector invalid
  [LIB_ARMCC_INCOMPATIBLE] DJI_Motor.lib cannot be linked by GCC
  [RTOS_PORT_MISMATCH] FreeRTOS RVDS port selected for GCC backend

Warnings:
  [OPENOCD_VENDOR_MISMATCH] openocd-esp32 used for STM32 target
  [CCMRAM_UNUSED] CCMRAM detected but not mapped
  [ARMCC_PRAGMA_DETECTED] #pragma arm section detected

Generated:
  .keilbridge/report/doctor_report.md
  .keilbridge/report/doctor_result.json
  .keilbridge/patches/armcc_to_gcc.patch
```

---

## 24. 开发优先级建议

### 阶段 1：Build Doctor

优先解释 GCC 编译失败：

```text
include 缺失
宏缺失
startup 错误
system_xxx.c 缺失
HAL/SPL 源文件缺失
RTOS port 错误
.lib 不兼容
```

这是性价比最高的。

### 阶段 2：ELF Doctor

检查：

```text
.isr_vector
Reset_Handler
_estack
.text/.data/.bss 地址
Flash/RAM 溢出
```

这能提前发现“编译过了但跑不起来”。

### 阶段 3：Debug Doctor

检查：

```text
OpenOCD/J-Link
serverpath
target cfg
reset halt 后 PC/MSP
Flash 向量表
lockup/hardfault
```

### 阶段 4：Compat Doctor

扫描 ARMCC 专用语法：

```text
__asm
__weak
__packed
__align
#pragma arm section
Image$$ 符号
```

生成兼容头和 patch。

### 阶段 5：Lib Doctor

把 `.lib` 问题产品化：

```text
找源码
找 GCC .a
推荐 ArmClang backend
保留 Keil backend
标记不可 GCC 迁移
```

### 阶段 6：Device Database

逐步补齐：

```text
STM32F1/F4/G4/H7
GD32F10x/F30x/L23x/E23x
CMSIS-Pack 解析
CubeMX .ioc 解析
OpenOCD/J-Link 映射
```

---

## 25. 最终建议

KeilBridge 的关键不是“永远成功”，而是：

```text
1. 自动转换常规工程
2. 对不兼容工程优雅降级
3. 对失败原因结构化诊断
4. 对可修复问题生成兼容层或 patch
5. 对硬边界问题明确告知用户
```

你应该让工具输出这种体验：

```text
这个工程不是简单失败；
而是：
    80% 已经转换完成，
    10% 需要 board.override.yaml 确认，
    5% 可以通过 compat header 解决，
    5% 因为 ARMCC .lib 无法进入 GCC 后端。
```

最终产品思路：

```text
KeilBridge = 迁移生成器 + 诊断器 + 兼容层生成器 + 后端推荐器
```

一句话总结：

```text
不要让用户面对 GCC 原始报错；
让用户面对 KeilBridge 的诊断结论。
```
