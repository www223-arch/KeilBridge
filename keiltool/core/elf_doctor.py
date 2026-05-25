from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import shutil
import subprocess

from keiltool.core.project_model import KeilTargetModel
from keiltool.core.tool_finder import find_arm_gcc_root


@dataclass(slots=True)
class ElfDoctorFinding:
    """ELF Doctor 诊断项。

    Flash Doctor 看探针/烧录链路，ELF Doctor 看“固件能不能按启动语义正常跑”。
    这里优先覆盖曾经真实踩过的坑：C++ 构造表缺失、RAM 自定义段成为 orphan、
    FreeRTOS 异常入口未映射等。
    """

    severity: str
    code: str
    title: str
    message: str
    evidence: str = ""
    suggestion: str = ""


@dataclass(slots=True)
class ElfDoctorResult:
    elf: str
    findings: list[ElfDoctorFinding]

    def to_dict(self) -> dict:
        return {
            "schema": "keilbridge.elf_doctor.v1",
            "elf": self.elf,
            "findings": [asdict(item) for item in self.findings],
        }


SECTION_RE = re.compile(
    r"^\s*(?P<idx>\d+)\s+(?P<name>\S+)\s+(?P<size>[0-9a-fA-F]+)\s+"
    r"(?P<vma>[0-9a-fA-F]+)\s+(?P<lma>[0-9a-fA-F]+)"
)


def run_elf_doctor(target: KeilTargetModel, workspace_root: Path, elf: Path | None = None, arm_gcc_root: str | None = None) -> ElfDoctorResult:
    """检查生成 ELF 的启动/链接语义。

    这一步不接触硬件，适合在 build 后立即运行。它不会证明业务逻辑一定正确，
    但可以提前拦住“能烧录、运行就炸”的典型生成层问题。
    """

    project_name = _sanitize_name(target.name)
    elf_path = elf or workspace_root / ".keilbridge" / "build" / "gcc-debug" / f"{project_name}.elf"
    if not elf_path.exists():
        return ElfDoctorResult(
            elf=str(elf_path),
            findings=[
                ElfDoctorFinding(
                    severity="fatal",
                    code="ELF_NOT_FOUND",
                    title="未找到 ELF",
                    message=f"ELF 不存在：{elf_path}",
                    suggestion="先执行 build，再运行 doctor elf。",
                )
            ],
        )

    objdump = _tool("objdump", arm_gcc_root)
    nm = _tool("nm", arm_gcc_root)
    sections_text = subprocess.check_output([objdump, "-h", str(elf_path)], text=True, errors="replace")
    symbols_text = subprocess.check_output([nm, "-n", "-C", str(elf_path)], text=True, errors="replace")
    sections = _parse_sections(sections_text)
    symbols = _parse_symbols(symbols_text)

    findings: list[ElfDoctorFinding] = []
    findings.extend(_check_required_symbols(symbols))
    findings.extend(_check_cpp_init(target, sections, symbols))
    findings.extend(_check_orphan_ram_sections(sections))
    findings.extend(_check_freertos_handlers(target, symbols))
    if not any(item.severity in {"fail", "fatal"} for item in findings):
        findings.append(
            ElfDoctorFinding(
                severity="pass",
                code="ELF_STARTUP_CHECKS_PASS",
                title="ELF 启动/链接基础检查通过",
                message="未发现 C++ 构造表、关键启动符号、RAM orphan 段或 FreeRTOS handler 映射的阻塞级问题。",
            )
        )
    return ElfDoctorResult(elf=str(elf_path), findings=findings)


def render_elf_doctor_markdown(result: ElfDoctorResult) -> str:
    lines = ["# KeilBridge ELF Doctor Report", "", f"- ELF: `{result.elf}`", "", "## Findings", ""]
    for item in result.findings:
        lines.extend([f"### [{item.severity}] {item.code}", "", item.title, "", item.message, ""])
        if item.evidence:
            lines.extend(["Evidence:", "", "```text", item.evidence, "```", ""])
        if item.suggestion:
            lines.extend(["Suggestion:", "", item.suggestion, ""])
    return "\n".join(lines).rstrip() + "\n"


def _check_required_symbols(symbols: dict[str, str]) -> list[ElfDoctorFinding]:
    required = ["Reset_Handler", "main", "_estack", "_sdata", "_edata", "_sidata", "_sbss", "_ebss"]
    missing = [item for item in required if item not in symbols]
    if not missing:
        return []
    return [
        ElfDoctorFinding(
            severity="fatal",
            code="ELF_REQUIRED_STARTUP_SYMBOLS_MISSING",
            title="ELF 缺少关键启动符号",
            message="启动文件和链接脚本没有形成完整的 data/bss/stack 符号契约。",
            evidence=", ".join(missing),
            suggestion="检查 startup_generator 和 GNU ld 脚本生成逻辑。",
        )
    ]


def _check_cpp_init(target: KeilTargetModel, sections: dict[str, dict[str, int]], symbols: dict[str, str]) -> list[ElfDoctorFinding]:
    has_cpp = any(source.path.lower().endswith((".cpp", ".cxx", ".cc")) for source in target.sources)
    has_vtable = any("vtable for " in name for name in symbols)
    if not has_cpp and not has_vtable:
        return []
    missing_symbols = [name for name in ["__libc_init_array", "__init_array_start", "__init_array_end"] if name not in symbols]
    init_size = sections.get(".init_array", {}).get("size", 0)
    if missing_symbols or init_size == 0:
        return [
            ElfDoctorFinding(
                severity="fail",
                code="CPP_STATIC_CONSTRUCTORS_NOT_LINKED",
                title="C++ 全局构造表缺失或为空",
                message="工程包含 C++/虚函数迹象，但 ELF 中没有可用的 init_array。全局 C++ 对象可能不会构造，运行到虚函数调用时容易 HardFault。",
                evidence=f"missing={missing_symbols}; .init_array size=0x{init_size:X}",
                suggestion="确认 Reset_Handler 调用 __libc_init_array，并在 linker script 中 KEEP .preinit_array/.init_array/.fini_array。",
            )
        ]
    return []


def _check_orphan_ram_sections(sections: dict[str, dict[str, int]]) -> list[ElfDoctorFinding]:
    allowed = {".data", ".bss", "._user_heap_stack", ".ccmram"}
    findings: list[ElfDoctorFinding] = []
    for name, section in sections.items():
        vma = section["vma"]
        size = section["size"]
        if size == 0 or name in allowed:
            continue
        in_sram = 0x20000000 <= vma < 0x30000000 or 0x10000000 <= vma < 0x10040000
        if in_sram:
            findings.append(
                ElfDoctorFinding(
                    severity="fail",
                    code="RAM_ORPHAN_SECTION_MAY_NOT_BE_INITIALIZED",
                    title="发现位于 RAM 的孤儿段",
                    message="该段不在 KeilBridge 明确管理的 data/bss/ccmram 范围中，startup 可能不会复制或清零它。",
                    evidence=f"{name}: VMA=0x{vma:08X}, size=0x{size:X}",
                    suggestion="把该输入段显式归入 .data、.bss、.ccmram，或为它增加专门的 startup copy/zero 逻辑。",
                )
            )
    return findings


def _check_freertos_handlers(target: KeilTargetModel, symbols: dict[str, str]) -> list[ElfDoctorFinding]:
    if "freertos" not in target.features.rtos:
        return []
    missing = [name for name in ["SVC_Handler", "PendSV_Handler", "SysTick_Handler"] if name not in symbols]
    if missing:
        return [
            ElfDoctorFinding(
                severity="fail",
                code="FREERTOS_EXCEPTION_HANDLERS_MISSING",
                title="FreeRTOS 关键异常入口缺失",
                message="FreeRTOS Cortex-M port 需要 SVC/PendSV/SysTick 入口。缺失时调度器可能无法启动或运行异常。",
                evidence=", ".join(missing),
                suggestion="检查 FreeRTOSConfig.h 的 handler mapping 和 GCC port.c 是否参与构建。",
            )
        ]
    return []


def _parse_sections(text: str) -> dict[str, dict[str, int]]:
    sections: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        match = SECTION_RE.match(line)
        if match:
            sections[match.group("name")] = {
                "size": int(match.group("size"), 16),
                "vma": int(match.group("vma"), 16),
                "lma": int(match.group("lma"), 16),
            }
    return sections


def _parse_symbols(text: str) -> dict[str, str]:
    symbols: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) >= 3:
            name = parts[-1]
            symbols[name] = parts[0]
    return symbols


def _tool(name: str, arm_gcc_root: str | None) -> str:
    exe = f"arm-none-eabi-{name}.exe"
    root = find_arm_gcc_root(arm_gcc_root)
    if root:
        candidate = Path(root) / "bin" / exe
        if candidate.exists():
            return str(candidate)
    found = shutil.which(exe)
    return found or exe


def _sanitize_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
