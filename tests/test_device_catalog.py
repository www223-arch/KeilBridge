from __future__ import annotations


def _device(name: str, source_kind: str):
    from keiltool.core.device_catalog import CatalogDevice, CatalogSource

    return CatalogDevice(
        vendor="GigaDevice",
        device=name,
        family="GD32F30x",
        sub_family="GD32F303",
        core="Cortex-M4",
        fpu="FPU",
        endian="Little-endian",
        memory=(),
        flash_algorithms=(),
        openocd_target="target/stm32f3x.cfg",
        openocd_status="verified" if source_kind == "embedded" else "user_provided",
        source=CatalogSource(
            kind=source_kind,
            vendor="GigaDevice",
            pack="GD32F30x_DFP",
            pack_version="2.5.0",
            location="test",
            digest="abc",
        ),
    )


def test_catalog_uses_exact_case_normalized_lookup_without_fuzzy_matching():
    from keiltool.core.device_catalog import DeviceCatalog

    embedded = _device("GD32F303VE", "embedded")
    catalog = DeviceCatalog(embedded=(embedded,))

    assert catalog.lookup("gigadevice", "gd32f303ve") == embedded
    assert catalog.lookup_any_vendor("GD32F303VE") == embedded
    assert catalog.lookup_any_vendor("GD32F303V") is None


def test_user_device_overrides_imported_and_embedded_record():
    from keiltool.core.device_catalog import DeviceCatalog

    embedded = _device("GD32F303VE", "embedded")
    imported = _device("GD32F303VE", "imported_pack")
    user = _device("GD32F303VE", "user")

    catalog = DeviceCatalog(
        embedded=(embedded,),
        imported=(imported,),
        user=(user,),
    )

    assert catalog.lookup("GigaDevice", "GD32F303VE") == user
    assert catalog.devices == (user,)
