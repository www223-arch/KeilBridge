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

    def to_dict(self) -> dict[str, object]:
        return {"version": SETTINGS_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: object) -> "GuiSettings":
        if not isinstance(data, dict):
            return cls()
        if "version" in data and data["version"] != SETTINGS_VERSION:
            return cls()
        defaults = cls()
        return cls(
            project=_string(data.get("project"), defaults.project),
            target=_string(data.get("target"), defaults.target),
            firmware=_string(data.get("firmware"), defaults.firmware),
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


def _rtt_level(value: object) -> str:
    if isinstance(value, str) and value in {level.name for level in RttLevel}:
        return value
    return RttLevel.VERBOSE.name
