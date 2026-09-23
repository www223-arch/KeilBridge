from pathlib import Path
import os


repo_root = Path(SPECPATH).resolve().parent
entry = repo_root / "packaging" / "rtt_collector_entry.py"
openocd_exe = Path(os.environ["KEILTOOL_BUILD_OPENOCD_EXE"])
openocd_scripts = Path(os.environ["KEILTOOL_BUILD_OPENOCD_SCRIPTS"])
openocd_root = openocd_exe.parent.parent

binaries = [(str(openocd_exe), "openocd/bin")]
for library_name in ("libusb-1.0.dll", "libftdi1.dll"):
    library = openocd_exe.parent / library_name
    if library.is_file():
        binaries.append((str(library), "openocd/bin"))

datas = [
    (str(repo_root / "keiltool" / "data"), "keiltool/data"),
    (str(openocd_scripts), "openocd/scripts"),
]
for source, destination in (
    (openocd_root / "distro-info", "openocd/distro-info"),
    (openocd_root / "README.md", "openocd"),
):
    if source.exists():
        datas.append((str(source), destination))

a = Analysis(
    [str(entry)],
    pathex=[str(repo_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="RTT-Collector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
