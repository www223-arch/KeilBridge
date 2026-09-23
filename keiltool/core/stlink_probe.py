from __future__ import annotations

import ctypes
from ctypes import util as ctypes_util
from dataclasses import dataclass
from pathlib import Path


_STLINK_VENDOR_ID = 0x0483
_STLINK_PRODUCT_IDS = frozenset(
    {
        0x3744,
        0x3748,
        0x374B,
        0x374D,
        0x374E,
        0x374F,
        0x3752,
        0x3753,
        0x3754,
    }
)


@dataclass(frozen=True, slots=True)
class UsbProbeRecord:
    bus: int
    ports: tuple[int, ...]
    product_id: int
    serial: str = ""

    @property
    def usb_location(self) -> str:
        route = ".".join(str(port) for port in self.ports)
        return f"{self.bus}-{route}" if route else ""


@dataclass(frozen=True, slots=True)
class StLinkProbe:
    identity: str
    product_id: int
    adapter_serial: str = ""
    adapter_usb_location: str = ""


@dataclass(frozen=True, slots=True)
class StLinkDiscovery:
    probes: tuple[StLinkProbe, ...]
    diagnostic: str = ""


def build_stlink_probes(records: tuple[UsbProbeRecord, ...]) -> tuple[StLinkProbe, ...]:
    ordered = tuple(sorted(records, key=lambda item: (item.bus, item.ports)))
    readable_serials = [_readable_serial(item.serial) for item in ordered]
    serial_counts = {
        serial: readable_serials.count(serial)
        for serial in set(readable_serials)
        if serial
    }
    probes: list[StLinkProbe] = []
    for record, serial in zip(ordered, readable_serials):
        location = record.usb_location
        identity = f"usb:{location}" if location else f"serial:{serial}"
        if serial and serial_counts.get(serial) == 1:
            probes.append(
                StLinkProbe(
                    identity=identity,
                    product_id=record.product_id,
                    adapter_serial=serial,
                )
            )
        elif location:
            probes.append(
                StLinkProbe(
                    identity=f"usb:{location}",
                    product_id=record.product_id,
                    adapter_usb_location=location,
                )
            )
    return tuple(probes)


def discover_stlink_probes(openocd_executable: str | Path) -> StLinkDiscovery:
    return _discover_stlink_probes(openocd_executable, read_serial=True)


def discover_stlink_probes_nonintrusive(
    openocd_executable: str | Path,
) -> StLinkDiscovery:
    """Enumerate probes without opening them to read USB string descriptors."""
    return _discover_stlink_probes(openocd_executable, read_serial=False)


def _discover_stlink_probes(
    openocd_executable: str | Path,
    *,
    read_serial: bool,
) -> StLinkDiscovery:
    try:
        library_path = _find_libusb(openocd_executable)
        if not library_path:
            return StLinkDiscovery((), "未找到 OpenOCD 自带的 USB 设备库。")
        records = _enumerate_usb_records(library_path, read_serial=read_serial)
        return StLinkDiscovery(build_stlink_probes(records))
    except (OSError, ValueError) as exc:
        return StLinkDiscovery((), f"无法读取 ST-Link 列表: {exc}")


def _readable_serial(value: str) -> str:
    serial = value.strip()
    if len(serial) < 4 or any(ord(character) < 0x20 or ord(character) > 0x7E for character in serial):
        return ""
    return serial


def _find_libusb(openocd_executable: str | Path) -> str:
    executable = Path(openocd_executable).expanduser()
    beside_openocd = executable.parent / "libusb-1.0.dll"
    if beside_openocd.is_file():
        return str(beside_openocd)
    discovered = ctypes_util.find_library("usb-1.0")
    return discovered or ""


class _LibusbDeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", ctypes.c_uint8),
        ("bDescriptorType", ctypes.c_uint8),
        ("bcdUSB", ctypes.c_uint16),
        ("bDeviceClass", ctypes.c_uint8),
        ("bDeviceSubClass", ctypes.c_uint8),
        ("bDeviceProtocol", ctypes.c_uint8),
        ("bMaxPacketSize0", ctypes.c_uint8),
        ("idVendor", ctypes.c_uint16),
        ("idProduct", ctypes.c_uint16),
        ("bcdDevice", ctypes.c_uint16),
        ("iManufacturer", ctypes.c_uint8),
        ("iProduct", ctypes.c_uint8),
        ("iSerialNumber", ctypes.c_uint8),
        ("bNumConfigurations", ctypes.c_uint8),
    ]


def _enumerate_usb_records(
    library_path: str,
    *,
    read_serial: bool = True,
) -> tuple[UsbProbeRecord, ...]:
    library = ctypes.CDLL(library_path)
    _configure_libusb(library)
    context = ctypes.c_void_p()
    result = library.libusb_init(ctypes.byref(context))
    if result != 0:
        raise OSError(f"libusb 初始化失败 ({result})")

    devices = ctypes.POINTER(ctypes.c_void_p)()
    count = library.libusb_get_device_list(context, ctypes.byref(devices))
    if count < 0:
        library.libusb_exit(context)
        raise OSError(f"libusb 枚举失败 ({count})")

    records: list[UsbProbeRecord] = []
    try:
        for index in range(count):
            device = devices[index]
            descriptor = _LibusbDeviceDescriptor()
            if library.libusb_get_device_descriptor(device, ctypes.byref(descriptor)) != 0:
                continue
            if descriptor.idVendor != _STLINK_VENDOR_ID or descriptor.idProduct not in _STLINK_PRODUCT_IDS:
                continue
            ports_buffer = (ctypes.c_uint8 * 8)()
            port_count = library.libusb_get_port_numbers(device, ports_buffer, len(ports_buffer))
            ports = tuple(int(ports_buffer[item]) for item in range(max(0, port_count)))
            serial = (
                _read_usb_string(library, device, descriptor.iSerialNumber)
                if read_serial
                else ""
            )
            records.append(
                UsbProbeRecord(
                    bus=int(library.libusb_get_bus_number(device)),
                    ports=ports,
                    product_id=int(descriptor.idProduct),
                    serial=serial,
                )
            )
    finally:
        library.libusb_free_device_list(devices, 1)
        library.libusb_exit(context)
    return tuple(records)


def _configure_libusb(library: ctypes.CDLL) -> None:
    library.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    library.libusb_init.restype = ctypes.c_int
    library.libusb_get_device_list.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ]
    library.libusb_get_device_list.restype = ctypes.c_ssize_t
    library.libusb_get_device_descriptor.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_LibusbDeviceDescriptor),
    ]
    library.libusb_get_device_descriptor.restype = ctypes.c_int
    library.libusb_get_bus_number.argtypes = [ctypes.c_void_p]
    library.libusb_get_bus_number.restype = ctypes.c_uint8
    library.libusb_get_port_numbers.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int,
    ]
    library.libusb_get_port_numbers.restype = ctypes.c_int
    library.libusb_open.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    library.libusb_open.restype = ctypes.c_int
    library.libusb_get_string_descriptor_ascii.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint8,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int,
    ]
    library.libusb_get_string_descriptor_ascii.restype = ctypes.c_int
    library.libusb_close.argtypes = [ctypes.c_void_p]
    library.libusb_free_device_list.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
    library.libusb_exit.argtypes = [ctypes.c_void_p]


def _read_usb_string(library: ctypes.CDLL, device: ctypes.c_void_p, index: int) -> str:
    if not index:
        return ""
    handle = ctypes.c_void_p()
    if library.libusb_open(device, ctypes.byref(handle)) != 0:
        return ""
    try:
        buffer = (ctypes.c_ubyte * 256)()
        size = library.libusb_get_string_descriptor_ascii(handle, index, buffer, len(buffer))
        if size <= 0:
            return ""
        return bytes(buffer[:size]).decode("ascii", errors="replace")
    finally:
        library.libusb_close(handle)


__all__ = [
    "StLinkDiscovery",
    "StLinkProbe",
    "UsbProbeRecord",
    "build_stlink_probes",
    "discover_stlink_probes",
    "discover_stlink_probes_nonintrusive",
]
