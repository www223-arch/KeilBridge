from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from keiltool.core.cmsis_pack import parse_pdsc_bytes
from keiltool.core.device_catalog import (
    CATALOG_PATH,
    CatalogDevice,
    load_catalog_file,
    write_catalog_file,
)


MANIFEST_PATH = Path(__file__).with_name("device_catalog_sources.json")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the embedded CMSIS device catalog.")
    parser.add_argument(
        "--source-dir",
        action="append",
        default=[],
        type=Path,
        help="Directory containing official PDSC snapshots; may be repeated.",
    )
    parser.add_argument("--output", type=Path, default=CATALOG_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed catalog is canonical and matches the source manifest.",
    )
    return parser.parse_args()


def _manifest() -> list[dict[str, str]]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sources = payload.get("sources", [])
    if payload.get("schema_version") != 1 or not isinstance(sources, list):
        raise ValueError("Unsupported device catalog source manifest.")
    return sources


def _source_bytes(source: dict[str, str], directories: list[Path]) -> bytes:
    name = source["name"]
    candidates: list[bytes] = []
    for directory in directories:
        candidate = directory / name
        if candidate.is_file():
            data = candidate.read_bytes()
            if hashlib.sha256(data).hexdigest() == source["sha256"]:
                return data
            candidates.append(data)
    with urlopen(source["url"], timeout=30) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() == source["sha256"]:
        return data
    if candidates:
        return candidates[0]
    return data


def _build(directories: list[Path]) -> tuple[CatalogDevice, ...]:
    merged: dict[tuple[str, str], CatalogDevice] = {}
    for source in _manifest():
        data = _source_bytes(source, directories)
        digest = hashlib.sha256(data).hexdigest()
        if digest != source["sha256"]:
            raise ValueError(
                f"SHA-256 mismatch for {source['name']}: expected "
                f"{source['sha256']}, got {digest}"
            )
        for device in parse_pdsc_bytes(
            data,
            location=source["url"],
            source_kind="embedded",
        ):
            target = source.get("openocd_target", "")
            if target:
                device = replace(
                    device,
                    openocd_target=target,
                    openocd_status="explicit_pack_compatibility",
                )
            merged[device.key] = device
    return tuple(sorted(merged.values(), key=lambda item: item.key))


def _check(path: Path) -> None:
    devices = load_catalog_file(path)
    with tempfile.TemporaryDirectory() as directory:
        generated = Path(directory) / "catalog.json"
        write_catalog_file(generated, devices)
        if generated.read_bytes() != path.read_bytes():
            raise ValueError(f"{path} is not in canonical deterministic form.")

    expected_digests = {item["sha256"] for item in _manifest()}
    actual_digests = {item.source.digest for item in devices}
    unknown = actual_digests - expected_digests
    if unknown:
        raise ValueError(f"Catalog contains unrecognized source digests: {sorted(unknown)}")
    missing = expected_digests - actual_digests
    if missing:
        raise ValueError(f"Catalog is missing source digests: {sorted(missing)}")


def main() -> int:
    args = _arguments()
    if args.check:
        _check(args.output)
        print(f"Catalog check passed: {args.output}")
        return 0

    devices = _build(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_catalog_file(args.output, devices)
    print(f"Wrote {len(devices)} devices to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
