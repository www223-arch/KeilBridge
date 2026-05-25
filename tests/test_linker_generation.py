from keiltool.core.project_model import MemoryRegion
from keiltool.core.scatter import generate_gnu_ld


def test_gnu_ld_keeps_cpp_static_constructor_sections():
    """链接脚本必须保留 C++ 全局构造表。

    GCC/newlib 的 `__libc_init_array()` 依赖 `__init_array_start/end` 等符号遍历
    全局对象构造函数。如果这些段被遗漏，带虚函数的全局 C++ 对象会只被 BSS 清零，
    vtable 指针保持 0，运行到虚函数调用时容易进入 HardFault。
    """

    script = generate_gnu_ld(
        [
            MemoryRegion(name="FLASH", origin="0x08000000", length="1024K"),
            MemoryRegion(name="RAM", origin="0x20000000", length="128K"),
            MemoryRegion(name="CCMRAM", origin="0x10000000", length="64K"),
        ]
    )

    assert "__preinit_array_start" in script
    assert "__init_array_start" in script
    assert "__init_array_end" in script
    assert "__fini_array_start" in script
    assert "KEEP(*(SORT(.init_array.*)))" in script
    assert "KEEP(*(.init_array*))" in script


def test_gnu_ld_collects_sram_custom_sections_into_data_copy_range():
    """`__SRAM` 这类自定义段不能成为 startup 复制不到的孤儿段。"""

    script = generate_gnu_ld(
        [
            MemoryRegion(name="FLASH", origin="0x08000000", length="1024K"),
            MemoryRegion(name="RAM", origin="0x20000000", length="128K"),
        ]
    )

    data_section = script.split(".data :", 1)[1].split("}>RAM AT> FLASH", 1)[0]
    assert "*(.SRAM)" in data_section
    assert "*(.SRAM*)" in data_section
