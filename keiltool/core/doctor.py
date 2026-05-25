from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
from time import strftime

from keiltool.core.project_model import KeilTargetModel
from keiltool.core.tool_finder import find_openocd, find_openocd_scripts


@dataclass(slots=True)
class DoctorFinding:
    """Doctor 诊断项。

    普通 diagnostics 更偏向工程静态扫描；DoctorFinding 面向某个阶段的真实执行现场，
    例如 OpenOCD 日志、GDB 返回、ELF 检查结果。它必须同时适合人读和后续 JSON 输出。
    """

    stage: str
    severity: str
    code: str
    title: str
    message: str
    evidence: str = ""
    suggestion: str = ""


@dataclass(slots=True)
class FlashDoctorResult:
    """Flash Doctor 的结构化结果。"""

    command: list[str]
    returncode: int | None
    stdout_log: str
    stderr_log: str
    findings: list[DoctorFinding]

    def to_dict(self) -> dict:
        return {
            "schema": "keilbridge.flash_doctor.v1",
            "command": self.command,
            "returncode": self.returncode,
            "stdout_log": self.stdout_log,
            "stderr_log": self.stderr_log,
            "findings": [asdict(item) for item in self.findings],
        }


def run_flash_doctor(
    target: KeilTargetModel,
    workspace_root: Path,
    probe: str,
    openocd_path: str | None = None,
    run_probe: bool = False,
) -> FlashDoctorResult:
    """执行或分析 Flash Doctor。

    默认不主动碰硬件，只分析 `.keilbridge` 中已有的 OpenOCD 日志。这符合零侵入原则：
    用户没有明确要求时，不反复 reset/占用调试器。传入 `run_probe=True` 时才启动一次
    OpenOCD，执行最小连接/复位/读向量表流程，并把 stdout/stderr 保存到 logs 目录。
    """

    bridge_dir = workspace_root / ".keilbridge"
    generated_dir = bridge_dir / "generated"
    logs_dir = bridge_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    project_name = _sanitize_name(target.name)
    cfg = generated_dir / "openocd" / f"{project_name}_{probe}.cfg"
    openocd = find_openocd(openocd_path)
    scripts = find_openocd_scripts(openocd)
    command = _openocd_doctor_command(openocd, scripts, cfg)
    findings = _static_flash_findings(target, openocd, cfg, probe)

    stdout_log = ""
    stderr_log = ""
    returncode: int | None = None
    if run_probe:
        stamp = strftime("%Y%m%d-%H%M%S")
        stdout_path = logs_dir / f"doctor_flash_{project_name}_{probe}_{stamp}.out.log"
        stderr_path = logs_dir / f"doctor_flash_{project_name}_{probe}_{stamp}.err.log"
        completed = subprocess.run(command, cwd=generated_dir, text=True, capture_output=True)
        returncode = completed.returncode
        stdout_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
        stderr_path.write_text(completed.stderr, encoding="utf-8", newline="\n")
        stdout_log = str(stdout_path)
        stderr_log = str(stderr_path)
        findings.extend(classify_openocd_log(completed.stdout + "\n" + completed.stderr, openocd, target, probe))
    else:
        # 兼容早期手工测试留下的日志名称，也扫描新的 logs 目录。先读已有日志，就能解释
        # VS Code/Cortex-Debug 报错，而不要求用户再次插拔或重新跑 OpenOCD。
        latest_doctor_logs = _latest_doctor_log_pair(logs_dir)
        log_paths = latest_doctor_logs or [
            bridge_dir / "openocd-debug-test.out.log",
            bridge_dir / "openocd-debug-test.err.log",
        ]
        text_parts: list[str] = []
        for path in log_paths:
            if path.exists():
                text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
                if path.suffixes[-2:] == [".out", ".log"]:
                    stdout_log = str(path)
                if path.suffixes[-2:] == [".err", ".log"]:
                    stderr_log = str(path)
        findings.extend(classify_openocd_log("\n".join(text_parts), openocd, target, probe))

    if not any(item.severity in {"fail", "fatal", "pass"} for item in findings):
        command_hint = (
            f'python -m keiltool.cli doctor flash --project "{target.project_file}" '
            f"--target {target.name} --probe {probe} --run"
        )
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="info",
                code="FLASH_DOCTOR_NO_FATAL_LOG_MATCH",
                title="未在现有日志中匹配到阻塞级 OpenOCD 错误",
                message="Flash Doctor 当前未发现连接或启动状态的阻塞级错误。注意：Doctor 不会下载新固件。",
                suggestion=f"若要重新采集现场，可运行：{command_hint}。若要真正烧录，请运行 `python -m keiltool.cli flash ...`。",
            )
        )

    return FlashDoctorResult(
        command=command,
        returncode=returncode,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        findings=findings,
    )


def classify_openocd_log(text: str, openocd_path: str, target: KeilTargetModel, probe: str) -> list[DoctorFinding]:
    """把 OpenOCD 原始日志转换为 KeilBridge 诊断结论。"""

    findings: list[DoctorFinding] = []
    lower = text.lower()
    if not text.strip():
        return findings

    if "cmsis-dap command cmd_info failed" in lower or "hid_write/waitforsingleobject" in lower:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="fail",
                code="CMSIS_DAP_CMD_INFO_FAILED",
                title="CMSIS-DAP/DAPLink 在 OpenOCD 初始化阶段失败",
                message="OpenOCD 已经启动，但在读取 CMSIS-DAP 探针信息时 HID 写入失败，调试服务随后退出。",
                evidence=_first_matching_line(text, ["CMD_INFO failed", "hid_write/WaitForSingleObject"]),
                suggestion=(
                    "先关闭 VS Code 中残留的 gdb-server/openocd 终端、串口监视器和其他调试软件；"
                    "再拔插 DAPLink 后重试。若仍失败，优先换用 xPack OpenOCD 或 STM32CubeCLT OpenOCD，"
                    "不要长期依赖 ESP-IDF 打包的 openocd-esp32 调试 STM32。"
                ),
            )
        )

    if "cmsis-dap command mismatch" in lower or "cmd_dap_swj_clock failed" in lower:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="fail",
                code="CMSIS_DAP_COMMAND_MISMATCH",
                title="CMSIS-DAP/DAPLink 烧录过程中命令响应错位",
                message=(
                    "OpenOCD 已经识别到目标芯片并开始烧录，但 CMSIS-DAP 探针返回的命令号和 OpenOCD "
                    "期望值不一致。这通常是探针固件、USB/HID 通信、旧 OpenOCD 进程占用或 OpenOCD "
                    "版本兼容性问题，不是 CMake 编译产物本身的错误。"
                ),
                evidence=_first_matching_line(text, ["CMSIS-DAP command mismatch", "CMD_DAP_SWJ_CLOCK failed"]),
                suggestion=(
                    "先结束 openocd.exe、arm-none-eabi-gdb.exe 和 VS Code gdb-server 终端，关闭串口监视器，"
                    "重新插拔 DAPLink 后重试。若仍复现，优先换用 xPack OpenOCD、STM32CubeCLT OpenOCD "
                    "或 DAPLink 官方建议的 OpenOCD；当前 ESP-IDF 打包的 openocd-esp32 不建议作为 STM32 "
                    "长期烧录/调试后端。"
                ),
            )
        )

    if "failed to write memory" in lower or "error writing to flash" in lower or "programming failed" in lower:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="fail",
                code="OPENOCD_FLASH_WRITE_FAILED",
                title="OpenOCD 写入 Flash 失败",
                message=(
                    "OpenOCD 已进入 program 阶段，但写 RAM 工作区或写 Flash 过程中失败。若日志同时出现 "
                    "CMSIS-DAP command mismatch，应优先按探针/OpenOCD 通信层问题处理。"
                ),
                evidence=_first_matching_line(text, ["Failed to write memory", "error writing to flash", "Programming Failed"]),
                suggestion=(
                    "确认没有其他程序占用调试器；降低 adapter speed 后重试；必要时改用独立 OpenOCD。"
                    "如果通信层稳定后仍失败，再检查读保护、Flash unlock、供电、SWD 线和目标 cfg。"
                ),
            )
        )

    if "error finishing flash operation" in lower:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="fail",
                code="OPENOCD_FLASH_OPERATION_FAILED",
                title="OpenOCD 烧录收尾失败",
                message="GDB target-download 或 OpenOCD program 在 flash operation 结束阶段失败。",
                evidence=_first_matching_line(text, ["Error finishing flash operation"]),
                suggestion="对 Cortex-Debug 配置保留 loadFiles: []，优先让 KeilBridge/OpenOCD CLI 完成 program verify，再让 VS Code 只连接符号调试。",
            )
        )

    if "verified ok" in lower or "programming finished" in lower:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="pass",
                code="OPENOCD_PROGRAM_VERIFY_OK",
                title="OpenOCD program/verify 已通过",
                message="日志显示固件曾经成功写入并校验通过。",
                evidence=_first_matching_line(text, ["Programming Finished", "Verified OK"]),
            )
        )

    if "pc: 0xfffffffe" in lower or "msp: 0xfffffffc" in lower:
        findings.append(
            DoctorFinding(
                stage="debug",
                severity="fail",
                code="RESET_VECTOR_APPEARS_EMPTY",
                title="复位后 PC/MSP 像空 Flash 向量表",
                message="OpenOCD 已经能连接并 halt，但复位现场显示 PC=0xFFFFFFFE 或 MSP=0xFFFFFFFC，程序通常不会正常进入 Reset_Handler。",
                evidence=_first_matching_line(text, ["pc: 0xfffffffe", "msp: 0xfffffffc"]),
                suggestion=(
                    "先执行一次 OpenOCD program/verify，把当前 ELF 烧进 Flash；"
                    "然后再 reset halt 并读取 0x08000000 前两个 word。"
                    "如果仍然是 0xFFFFFFFF/0xFFFFFFFE，需要检查 bootloader offset、FLASH ORIGIN、"
                    "读保护/擦写失败或启动地址配置。"
                ),
            )
        )
    elif "pc: 0x080" in lower and "msp: 0x200" in lower:
        findings.append(
            DoctorFinding(
                stage="debug",
                severity="pass",
                code="RESET_STATE_LOOKS_VALID",
                title="复位后 PC/MSP 看起来有效",
                message="OpenOCD reset/halt 后 PC 落在 Flash 区，MSP 落在 SRAM 区，启动向量状态基本可信。",
                evidence=_first_matching_line(text, ["pc: 0x080", "msp: 0x200"]),
            )
        )

    return findings


def render_flash_doctor_markdown(result: FlashDoctorResult, target: KeilTargetModel, probe: str) -> str:
    """生成面向用户的 Flash Doctor 报告。"""

    lines = [
        "# KeilBridge Flash Doctor Report",
        "",
        f"- Target: `{target.name}`",
        f"- Device: `{target.device}`",
        f"- Probe: `{probe}`",
        f"- Return code: `{result.returncode if result.returncode is not None else 'not run'}`",
        f"- Stdout log: `{result.stdout_log or 'not available'}`",
        f"- Stderr log: `{result.stderr_log or 'not available'}`",
        "",
        "## Command",
        "",
        "```powershell",
        " ".join(f'"{item}"' if " " in item else item for item in result.command),
        "```",
        "",
        "## Findings",
        "",
    ]
    for item in result.findings:
        lines.extend(
            [
                f"### [{item.severity}] {item.code}",
                "",
                item.title,
                "",
                item.message,
                "",
            ]
        )
        if item.evidence:
            lines.extend(["Evidence:", "", "```text", item.evidence, "```", ""])
        if item.suggestion:
            lines.extend(["Suggestion:", "", item.suggestion, ""])
    return "\n".join(lines).rstrip() + "\n"


def _static_flash_findings(target: KeilTargetModel, openocd: str, cfg: Path, probe: str) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    openocd_lower = openocd.replace("\\", "/").lower()
    if "openocd-esp32" in openocd_lower or "esp_idf" in openocd_lower or "espressif" in openocd_lower:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="warn",
                code="OPENOCD_ESP32_FOR_STM32_GD32",
                title="当前 OpenOCD 来自 ESP-IDF 打包版本",
                message=f"当前 serverpath 是 `{openocd}`，目标芯片是 `{target.device}`。",
                suggestion="ESP-IDF OpenOCD 主要面向 ESP 芯片。STM32/GD32 调试建议优先使用 xPack OpenOCD、STM32CubeCLT OpenOCD 或系统独立 OpenOCD。",
            )
        )
    if not cfg.exists():
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="fatal",
                code="OPENOCD_CONFIG_MISSING",
                title="OpenOCD 配置文件不存在",
                message=f"未找到 `{cfg}`。",
                suggestion="先运行 configure 重新生成 `.keilbridge/generated/openocd`。",
            )
        )
    if probe in {"cmsis-dap", "daplink"}:
        findings.append(
            DoctorFinding(
                stage="flash",
                severity="info",
                code="CMSIS_DAP_PROBE_SELECTED",
                title="当前使用 CMSIS-DAP/DAPLink 探针",
                message="CMSIS-DAP 通过 HID 或 WinUSB 访问，容易被旧 OpenOCD、串口工具或其他调试器占用。",
                suggestion="如果出现 CMD_INFO failed，先结束 openocd.exe/arm-none-eabi-gdb.exe，再关闭串口监视器并重新插拔 DAPLink。",
            )
        )
    return findings


def _openocd_doctor_command(openocd: str, scripts: str, cfg: Path) -> list[str]:
    command = [openocd]
    if scripts:
        command.extend(["-s", scripts])
    command.extend(
        [
            "-f",
            str(cfg),
            "-c",
            "init; reset halt; mdw 0x08000000 2; shutdown",
        ]
    )
    return command


def _latest_doctor_log_pair(logs_dir: Path) -> list[Path]:
    """返回最近一次 Doctor 运行产生的 stdout/stderr 日志。

    旧日志和新日志混读会制造“同时存在多个故障”的错觉。Flash/Debug Doctor 默认应该解释
    最新现场；只有没有 Doctor 日志时，才回退到早期手工 OpenOCD 测试日志。
    """

    err_logs = sorted(logs_dir.glob("doctor_flash_*.err.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not err_logs:
        return []
    latest_err = err_logs[0]
    prefix = latest_err.name.removesuffix(".err.log")
    latest_out = logs_dir / f"{prefix}.out.log"
    return [path for path in [latest_out, latest_err] if path.exists()]


def _first_matching_line(text: str, tokens: list[str]) -> str:
    lines = []
    for line in text.splitlines():
        if any(token.lower() in line.lower() for token in tokens):
            lines.append(line)
    return "\n".join(lines[:6])


def _sanitize_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
