from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from typing import Any


SCHEMA = "keiltool.hardware.v1"


def operation_payload(
    command: str,
    context: object,
    result: object,
    *,
    artifact: dict[str, object] | None = None,
) -> dict[str, object]:
    config = getattr(context, "config")
    findings = [_finding_payload(item) for item in getattr(result, "findings", [])]
    return {
        "schema": SCHEMA,
        "command": command,
        "success": bool(getattr(result, "success", False)),
        "outcome": str(getattr(result, "outcome", "failed")),
        "device": str(getattr(context, "device", "")),
        "source": str(getattr(context, "source", "")),
        "target": str(getattr(context, "target_name", "")),
        "openocd": {
            "target_cfg": str(getattr(config, "target_cfg", "")),
            "interface_cfg": str(getattr(config, "interface_cfg", "")),
            "returncode": int(getattr(result, "returncode", 1)),
            "command": [str(item) for item in getattr(result, "command", [])],
            "stdout_log": str(getattr(result, "stdout_log", "")),
            "stderr_log": str(getattr(result, "stderr_log", "")),
        },
        "artifact": _json_value(artifact or {}),
        "findings": findings,
    }


def render_operation(payload: dict[str, object], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    status = "SUCCESS" if payload["success"] else "FAILED"
    openocd = payload["openocd"]
    assert isinstance(openocd, dict)
    print(f"Command: {payload['command']}")
    print(f"Status: {status} ({payload['outcome']})")
    print(f"Device: {payload['device']}")
    print(f"Source: {payload['source']}")
    print(f"Target cfg: {openocd['target_cfg']}")
    print(f"OpenOCD exit code: {openocd['returncode']}")
    print(f"stdout log: {openocd['stdout_log']}")
    print(f"stderr log: {openocd['stderr_log']}")
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        for key, value in artifact.items():
            print(f"Artifact {key}: {value}")
    findings = payload.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                print(
                    f"[{finding.get('severity', 'unknown')}] "
                    f"{finding.get('code', '')}: {finding.get('title', '')}"
                )


def _finding_payload(value: object) -> dict[str, object]:
    if is_dataclass(value):
        payload = asdict(value)
    else:
        payload = {
            name: getattr(value, name)
            for name in (
                "stage",
                "severity",
                "code",
                "title",
                "message",
                "evidence",
                "suggestion",
            )
            if hasattr(value, name)
        }
    return _json_value(payload)


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


__all__ = ["SCHEMA", "operation_payload", "render_operation"]
