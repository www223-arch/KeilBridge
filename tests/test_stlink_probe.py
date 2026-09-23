from pathlib import Path

from keiltool.core.stlink_probe import (
    UsbProbeRecord,
    build_stlink_probes,
    discover_stlink_probes_nonintrusive,
)
from keiltool.gui.probe_preferences import ProbePreferenceStore


def test_probe_discovery_uses_unique_readable_serial_and_falls_back_for_clones():
    probes = build_stlink_probes(
        (
            UsbProbeRecord(bus=1, ports=(2,), product_id=0x374F, serial="066DFF123456"),
            UsbProbeRecord(bus=2, ports=(3,), product_id=0x3748, serial="clone"),
            UsbProbeRecord(bus=3, ports=(4, 1), product_id=0x3748, serial="clone"),
            UsbProbeRecord(bus=4, ports=(5,), product_id=0x3748, serial="bad\x06value"),
        )
    )

    assert probes[0].identity == "usb:1-2"
    assert probes[0].adapter_serial == "066DFF123456"
    assert probes[0].adapter_usb_location == ""
    assert probes[1].identity == "usb:2-3"
    assert probes[1].adapter_usb_location == "2-3"
    assert probes[2].identity == "usb:3-4.1"
    assert probes[3].identity == "usb:4-5"


def test_probe_preferences_remember_human_alias_and_project_binding(tmp_path):
    store = ProbePreferenceStore(tmp_path / "stlink-probes.json")
    context = "project:d:/fw/dragon.uvprojx::Debug"

    store.set_alias("usb:2-3", "Dragon 主板")
    store.set_binding(context, "usb:2-3")

    reopened = ProbePreferenceStore(store.path)
    assert reopened.alias_for("usb:2-3") == "Dragon 主板"
    assert reopened.binding_for(context) == "usb:2-3"

    reopened.set_binding(context, "usb:3-4.1")
    assert reopened.alias_for("usb:2-3") == "Dragon 主板"
    assert reopened.binding_for(context) == "usb:3-4.1"

    reopened.set_binding(context, "")
    assert reopened.binding_for(context) == ""


def test_probe_preferences_recover_from_invalid_json(tmp_path):
    path = tmp_path / "stlink-probes.json"
    path.write_text("{broken", encoding="utf-8")

    store = ProbePreferenceStore(path)

    assert store.alias_for("usb:2-3") == ""
    assert store.binding_for("project:any") == ""


def test_nonintrusive_probe_discovery_does_not_read_usb_serial(monkeypatch):
    import keiltool.core.stlink_probe as probe_module

    calls = []
    monkeypatch.setattr(probe_module, "_find_libusb", lambda _openocd: "libusb.dll")
    monkeypatch.setattr(
        probe_module,
        "_enumerate_usb_records",
        lambda _library, *, read_serial: calls.append(read_serial)
        or (UsbProbeRecord(2, (1, 4), 0x3748),),
    )

    discovery = discover_stlink_probes_nonintrusive("openocd.exe")

    assert calls == [False]
    assert discovery.probes[0].adapter_usb_location == "2-1.4"
