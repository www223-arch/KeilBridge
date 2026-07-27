from __future__ import annotations


def test_firmware_change_requires_explicit_acceptance(tmp_path):
    from keiltool.gui.firmware_freshness import FirmwareFreshness

    firmware = tmp_path / "app.bin"
    firmware.write_bytes(b"old")
    freshness = FirmwareFreshness()
    original = freshness.accept(firmware)
    assert freshness.accepts_path(firmware)

    firmware.write_bytes(b"new-version")
    change = freshness.observe(firmware)

    assert change is not None
    assert change.previous == original
    assert change.current is not None
    assert change.current.sha256 != original.sha256
    assert freshness.is_current(firmware) is False
    assert not freshness.accepts_path(firmware)

    freshness.accept_pending()

    assert freshness.is_current(firmware) is True
    assert freshness.accepts_path(firmware)


def test_declined_version_is_not_prompted_repeatedly_and_remains_stale(tmp_path):
    from keiltool.gui.firmware_freshness import FirmwareFreshness

    firmware = tmp_path / "app.hex"
    firmware.write_text("old", encoding="ascii")
    freshness = FirmwareFreshness()
    freshness.accept(firmware)
    firmware.write_text("new", encoding="ascii")

    assert freshness.observe(firmware) is not None
    assert freshness.observe(firmware) is None
    assert freshness.is_current(firmware) is False


def test_missing_firmware_is_stale_and_reselection_clears_state(tmp_path):
    from keiltool.gui.firmware_freshness import FirmwareFreshness

    firmware = tmp_path / "app.bin"
    firmware.write_bytes(b"data")
    freshness = FirmwareFreshness()
    freshness.accept(firmware)
    firmware.unlink()

    change = freshness.observe(firmware)

    assert change is not None
    assert change.current is None
    assert change.error
    assert freshness.is_current(firmware) is False

    firmware.write_bytes(b"replacement")
    freshness.accept(firmware)
    assert freshness.is_current(firmware) is True
