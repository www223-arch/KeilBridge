from __future__ import annotations

import json
from pathlib import Path

from keiltool.gui.settings import default_settings_path


_VERSION = 1


class ProbePreferenceStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path)
            if path is not None
            else default_settings_path().with_name("stlink-probes.json")
        )

    def alias_for(self, identity: str) -> str:
        aliases, _bindings = self._load()
        return aliases.get(identity, "")

    def binding_for(self, context: str) -> str:
        _aliases, bindings = self._load()
        return bindings.get(context, "")

    def set_alias(self, identity: str, alias: str) -> None:
        aliases, bindings = self._load()
        cleaned = alias.strip()
        if cleaned:
            aliases[identity] = cleaned
        else:
            aliases.pop(identity, None)
        self._save(aliases, bindings)

    def set_binding(self, context: str, identity: str) -> None:
        if not context:
            return
        aliases, bindings = self._load()
        if identity:
            bindings[context] = identity
        else:
            bindings.pop(context, None)
        self._save(aliases, bindings)

    def _load(self) -> tuple[dict[str, str], dict[str, str]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}, {}
        if not isinstance(payload, dict) or payload.get("version") != _VERSION:
            return {}, {}
        return _string_map(payload.get("aliases")), _string_map(payload.get("bindings"))

    def _save(self, aliases: dict[str, str], bindings: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(
                {"version": _VERSION, "aliases": aliases, "bindings": bindings},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(self.path)


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


__all__ = ["ProbePreferenceStore"]
