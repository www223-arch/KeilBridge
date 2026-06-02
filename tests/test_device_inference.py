from keiltool.core.device_inference import parse_memory_regions


def test_parse_memory_regions_supports_keil_origin_size_format():
    memory = parse_memory_regions('IRAM(0x20000000,0x0C000) IROM(0x08000000,0x040000) CPUTYPE("Cortex-M4") FPU2')

    assert [(item.name, item.origin, item.length) for item in memory] == [
        ("RAM", "0x20000000", "48K"),
        ("FLASH", "0x08000000", "256K"),
    ]
