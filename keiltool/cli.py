from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .core.diagnostics import diagnose_target
from .core.keil_parser import parse_uvprojx
from .core.scatter import generate_gnu_ld, parse_scatter_memory


def _pick_target(model, target_name: str | None):
    """选择 Keil Target。

    不指定 target 时沿用 Keil 文件中的第一个 Target，后续可以改成读取 uvoptx
    的当前活动 target。
    """

    if not model.targets:
        raise SystemExit("No targets found in Keil project.")
    if target_name is None:
        return model.targets[0]
    for target in model.targets:
        if target.name == target_name:
            return target
    names = ", ".join(target.name for target in model.targets)
    raise SystemExit(f"Target not found: {target_name}. Available targets: {names}")


def cmd_inspect(args: argparse.Namespace) -> int:
    """打印工程摘要，用于第一阶段快速验证 parser 是否理解 Keil 工程。"""

    model = parse_uvprojx(args.project)
    target = _pick_target(model, args.target)

    print(f"Project: {model.project_file}")
    print(f"Project root: {model.inferred_project_root}")
    print(f"Target: {target.name}")
    print(f"Device: {target.device or '(unknown)'}")
    print(f"Vendor/family: {(target.vendor or 'unknown')}/{(target.family or 'unknown')}")
    print(f"Core: {target.core or '(unknown)'}")
    print(f"FPU/float ABI: {(target.fpu or 'none')}/{target.float_abi or 'unknown'}")
    print(f"Device database: {'matched' if target.device_info.matched else 'not matched'}")
    if target.device_info.openocd_target:
        print(f"OpenOCD target: {target.device_info.openocd_target}")
    print(f"CPU: {target.cpu or '(not specified)'}")
    if target.memory:
        memory = ", ".join(f"{region.name} {region.origin}+{region.length}" for region in target.memory)
        print(f"Memory: {memory}")
    print(f"C standard: {target.c_standard}")
    print(f"Sources: {len(target.sources)}")
    print(f"Includes: {len(target.includes)}")
    print(f"Defines: {len(target.defines)}")
    print(f"Libraries: {len(target.libraries)}")
    print(f"Startup files: {len(target.startup_files)}")
    print(f"Scatter file: {target.scatter_file or '(none)'}")
    print(f"Scatter candidates: {len(target.scatter_candidates)}")

    if args.verbose:
        print("\nDefines:")
        for item in target.defines:
            print(f"  {item}")
        print("\nSource groups:")
        groups: dict[str, int] = {}
        for source in target.sources:
            groups[source.group or "(ungrouped)"] = groups.get(source.group or "(ungrouped)", 0) + 1
        for group, count in sorted(groups.items()):
            print(f"  {group}: {count}")
        if target.scatter_candidates:
            print("\nScatter candidates:")
            for path in target.scatter_candidates:
                print(f"  {path}")

    diagnostics = diagnose_target(target)
    if diagnostics:
        print("\nDiagnostics:")
        for diagnostic in diagnostics:
            print(f"  [{diagnostic.level}] {diagnostic.code}: {diagnostic.message}")
            if args.verbose and diagnostic.detail:
                print(f"    {diagnostic.detail}")

    return 0


def cmd_scatter(args: argparse.Namespace) -> int:
    """检查 Keil scatter，并可预览转换后的 GNU ld 脚本。"""

    model = parse_uvprojx(args.project)
    target = _pick_target(model, args.target)

    scatter_file = target.scatter_file
    if not scatter_file and target.scatter_candidates:
        scatter_file = target.scatter_candidates[0]
    if not scatter_file:
        raise SystemExit("No scatter file found. Memory can still be inferred from Cpu metadata, but there is no .sct to convert.")

    memory = parse_scatter_memory(scatter_file)
    print(f"Scatter: {scatter_file}")
    for region in memory:
        print(f"  {region.name}: {region.origin}+{region.length}")

    if args.emit_ld:
        print("\n# Generated GNU ld preview")
        print(generate_gnu_ld(memory))

    return 0


def cmd_model(args: argparse.Namespace) -> int:
    """输出 JSON 中间模型，方便后续测试和 generator 调试。"""

    model = parse_uvprojx(args.project)
    if args.target:
        target = _pick_target(model, args.target)
        payload = {
            "project_file": model.project_file,
            "keil_project_dir": model.keil_project_dir,
            "inferred_project_root": model.inferred_project_root,
            "target": asdict(target),
        }
    else:
        payload = model.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="k2c", description="Keil external CMake adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Print a Keil project summary")
    inspect_parser.add_argument("project", type=Path, help="Path to .uvprojx")
    inspect_parser.add_argument("--target", help="Keil target name")
    inspect_parser.add_argument("-v", "--verbose", action="store_true", help="Print additional details")
    inspect_parser.set_defaults(func=cmd_inspect)

    model_parser = subparsers.add_parser("model", help="Print normalized JSON model")
    model_parser.add_argument("project", type=Path, help="Path to .uvprojx")
    model_parser.add_argument("--target", help="Keil target name")
    model_parser.set_defaults(func=cmd_model)

    scatter_parser = subparsers.add_parser("scatter", help="Inspect or convert Keil scatter file")
    scatter_parser.add_argument("project", type=Path, help="Path to .uvprojx")
    scatter_parser.add_argument("--target", help="Keil target name")
    scatter_parser.add_argument("--emit-ld", action="store_true", help="Print GNU ld script preview")
    scatter_parser.set_defaults(func=cmd_scatter)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
