from __future__ import annotations


def generate_arm_math_compat() -> str:
    """生成 CMSIS-DSP 最小兼容层。

    你的样例工程目前只实际调用 `arm_sin_f32/arm_cos_f32`。原工程链接的是
    ARMCC `.lib`，GCC 不能直接使用，所以 MVP 先生成一个小型兼容源文件，
    后续再升级为“自动选择 GCC 版 CMSIS-DSP 库或源码构建”。
    """

    return """#include <math.h>

#ifndef __FPU_PRESENT
#define __FPU_PRESENT 1U
#endif

#include "arm_math.h"

float32_t arm_sin_f32(float32_t x)
{
    return sinf(x);
}

float32_t arm_cos_f32(float32_t x)
{
    return cosf(x);
}
"""


def generate_syscalls() -> str:
    """生成 newlib/nano 需要的最小系统调用桩。

    CubeMX 工程不一定自带 `syscalls.c`。为了让外部 GCC 链接闭环稳定，
    这里生成最小实现；真实串口重定向后续可以作为 profile 配置。
    """

    return """#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <signal.h>

void _exit(int status)
{
    (void)status;
    while (1) {
    }
}

int _close(int file)
{
    (void)file;
    return -1;
}

int _fstat(int file, struct stat *st)
{
    (void)file;
    st->st_mode = S_IFCHR;
    return 0;
}

int _isatty(int file)
{
    (void)file;
    return 1;
}

int _lseek(int file, int ptr, int dir)
{
    (void)file;
    (void)ptr;
    (void)dir;
    return 0;
}

int _read(int file, char *ptr, int len)
{
    (void)file;
    (void)ptr;
    (void)len;
    return 0;
}

int _write(int file, char *ptr, int len)
{
    (void)file;
    (void)ptr;
    return len;
}

int _getpid(void)
{
    return 1;
}

int _kill(int pid, int sig)
{
    (void)pid;
    (void)sig;
    errno = EINVAL;
    return -1;
}

caddr_t _sbrk(int incr)
{
    extern char end;
    static char *heap_end;
    char *prev_heap_end;

    if (heap_end == 0) {
        heap_end = &end;
    }

    prev_heap_end = heap_end;
    heap_end += incr;
    return (caddr_t)prev_heap_end;
}
"""
