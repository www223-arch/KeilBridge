from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any

from keiltool.core.rtt_log import RttLevel


SETTINGS_VERSION = 1


@dataclass(frozen=True, slots=True)
class GuiSettings:
    project: str = ""
    target: str = ""
    firmware: str = ""
    bin_address: str = "0x08000000"
    openocd_path: str = ""
    scripts_dir: str = ""
    target_override: str = ""
    rtt_address: str = ""
    rtt_channel: int = 0
    rtt_port: int = 19021
    rtt_timeout_ms: int = 5000
    rtt_display_level: str = "VERBOSE"
    logs_dir: str = ""
    device_vendor: str = ""
    device_name: str = ""
    device_source_mode: str = "device"
    project_firmware: str = ""
    device_firmware: str = ""
    vofa_path: str = ""
    vofa_listen: str = "127.0.0.1:1347"
    vofa_scope_profile: str = "bilbopro-imu-scope-v1"
    vofa_verify_scope_name: bool = True

    def to_dict(self) -> dict[str, object]:
        return {"version": SETTINGS_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: object) -> "GuiSettings":
        if not isinstance(data, dict):
            return cls()
        if "version" in data and data["version"] != SETTINGS_VERSION:
            return cls()
        defaults = cls()
        project = _string(data.get("project"), defaults.project)
        firmware = _string(data.get("firmware"), defaults.firmware)
        source_mode = _device_source_mode(data.get("device_source_mode"), project)
        return cls(
            project=project,
            target=_string(data.get("target"), defaults.target),
            firmware=firmware,
            bin_address=_string(data.get("bin_address"), defaults.bin_address),
            openocd_path=_string(data.get("openocd_path"), defaults.openocd_path),
            scripts_dir=_string(data.get("scripts_dir"), defaults.scripts_dir),
            target_override=_string(data.get("target_override"), defaults.target_override),
            rtt_address=_string(data.get("rtt_address"), defaults.rtt_address),
            rtt_channel=_integer(data.get("rtt_channel"), defaults.rtt_channel),
            rtt_port=_integer(data.get("rtt_port"), defaults.rtt_port),
            rtt_timeout_ms=_integer(data.get("rtt_timeout_ms"), defaults.rtt_timeout_ms),
            rtt_display_level=_rtt_level(data.get("rtt_display_level")),
            logs_dir=_string(data.get("logs_dir"), defaults.logs_dir),
            device_vendor=_string(data.get("device_vendor"), defaults.device_vendor),
            device_name=_string(data.get("device_name"), defaults.device_name),
            device_source_mode=source_mode,
            project_firmware=_string(
                data.get("project_firmware"),
                firmware if project else "",
            ),
            device_firmware=_string(
                data.get("device_firmware"),
                firmware if not project else "",
            ),
            vofa_path=_string(data.get("vofa_path"), defaults.vofa_path),
            vofa_listen=_string(data.get("vofa_listen"), defaults.vofa_listen),
            vofa_scope_profile=_string(
                data.get("vofa_scope_profile"),
                defaults.vofa_scope_profile,
            ),
            vofa_verify_scope_name=_boolean(
                data.get("vofa_verify_scope_name"),
                defaults.vofa_verify_scope_name,
            ),
        )


@dataclass(frozen=True, slots=True)
class SettingsDiagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SettingsLoadResult:
    settings: GuiSettings
    diagnostic: SettingsDiagnostic | None = None


class SettingsStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self) -> GuiSettings:
        return self.load_result().settings

    def load_result(self) -> SettingsLoadResult:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return SettingsLoadResult(GuiSettings())
        except OSError as exc:
            return SettingsLoadResult(
                GuiSettings(),
                SettingsDiagnostic("settings_unreadable", f"Unable to read settings from {self.path}: {exc}"),
            )
        except UnicodeDecodeError as exc:
            return SettingsLoadResult(
                GuiSettings(),
                SettingsDiagnostic("settings_corrupt", f"Settings are not valid UTF-8: {exc}"),
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return SettingsLoadResult(
                GuiSettings(),
                SettingsDiagnostic("settings_corrupt", f"Settings JSON is invalid: {exc}"),
            )
        if not isinstance(data, dict) or data.get("version") != SETTINGS_VERSION:
            return SettingsLoadResult(
                GuiSettings(),
                SettingsDiagnostic(
                    "settings_incompatible",
                    f"Settings format is incompatible with version {SETTINGS_VERSION}.",
                ),
            )
        return SettingsLoadResult(GuiSettings.from_dict(data))

    def save(self, settings: GuiSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        temporary_path.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary_path.replace(self.path)


def default_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base_dir = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base_dir / "KeilTool" / "gui-settings.json"


def default_devices_path() -> Path:
    return default_settings_path().parent / "devices"


def _string(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _integer(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _boolean(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _device_source_mode(value: object, project: str) -> str:
    if value in {"project", "device"}:
        return str(value)
    return "project" if project else "device"


def _rtt_level(value: object) -> str:
    if isinstance(value, str) and value in {level.name for level in RttLevel}:
        return value
    return RttLevel.VERBOSE.name
