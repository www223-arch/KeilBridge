from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil


_VOFA_1_3_CONFIG_VERSION = 100
_VOFA_1_3_TCP_CLIENT_INDEX = 2


@dataclass(frozen=True, slots=True)
class VofaConnectionConfigResult:
    configured: bool
    changed: bool
    config_path: Path | None
    backup_path: Path | None = None
    message: str = ""


def configure_vofa_1_3_connection(
    config_path: str | Path,
    host: str,
    port: int,
) -> VofaConnectionConfigResult:
    path = Path(config_path)
    if not host or any(character.isspace() for character in host):
        raise ValueError("VOFA TCP server host must not be empty or contain whitespace.")
    if not 1 <= port <= 65535:
        raise ValueError("VOFA TCP server port must be between 1 and 65535.")
    original_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(original_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"VOFA+ configuration is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("vnumber") != _VOFA_1_3_CONFIG_VERSION:
        raise ValueError("Only the verified VOFA+ 1.3 configuration format is supported.")
    try:
        pal = payload["ctx"]["wave_view"]["ctx"]["left_panel"]["ctx"]["pal"]["ctx"]
        tcp_client = pal["tcp_client"]
    except (KeyError, TypeError) as exc:
        raise ValueError("VOFA+ 1.3 connection settings were not found in the configuration.") from exc
    if not isinstance(pal, dict) or not isinstance(tcp_client, dict):
        raise ValueError("VOFA+ 1.3 connection settings have an unexpected format.")

    expected_port = str(port)
    changed = any(
        (
            tcp_client.get("server_ip") != host,
            str(tcp_client.get("server_port")) != expected_port,
            pal.get("protocol_combo") != "JustFloat",
            pal.get("link_type_combo") != _VOFA_1_3_TCP_CLIENT_INDEX,
        )
    )
    if not changed:
        return VofaConnectionConfigResult(True, False, path.resolve())

    tcp_client["server_ip"] = host
    tcp_client["server_port"] = expected_port
    pal["protocol_combo"] = "JustFloat"
    pal["link_type_combo"] = _VOFA_1_3_TCP_CLIENT_INDEX

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.stem}.{stamp}.keiltool-backup.json")
    shutil.copy2(path, backup)
    temporary = path.with_name(f".{path.name}.keiltool.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return VofaConnectionConfigResult(True, True, path.resolve(), backup.resolve())


def prepare_installed_vofa_connection(
    executable: str | Path,
    host: str,
    port: int,
) -> VofaConnectionConfigResult:
    executable_path = Path(executable)
    if not executable_path.is_file():
        return VofaConnectionConfigResult(
            False,
            False,
            None,
            message=f"VOFA+ executable does not exist: {executable_path}",
        )
    local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    candidates = (
        local_appdata / "VOFA+" / "100" / "context" / "vofa+.config.json",
        local_appdata / "vofa+" / "100" / "context" / "vofa+.config.json",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            return configure_vofa_1_3_connection(candidate, host, port)
        except (OSError, ValueError) as exc:
            return VofaConnectionConfigResult(
                False,
                False,
                candidate.resolve(),
                message=str(exc),
            )
    return VofaConnectionConfigResult(
        False,
        False,
        None,
        message="VOFA+ 1.3 configuration file was not found.",
    )


__all__ = [
    "VofaConnectionConfigResult",
    "configure_vofa_1_3_connection",
    "prepare_installed_vofa_connection",
]
