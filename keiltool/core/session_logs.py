from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SessionLogContext:
    directory: Path
    primary_log: Path
    stdout_log: Path
    stderr_log: Path
    metadata_log: Path
    device: str
    task: str
    started_at: datetime

    @property
    def rtt_log(self) -> Path:
        return self.primary_log

    def finalize(self, outcome: str, *, ended_at: datetime | None = None) -> None:
        ended = ended_at or datetime.now().astimezone()
        metadata = json.loads(self.metadata_log.read_text(encoding="utf-8"))
        metadata.update(
            {
                "outcome": outcome,
                "ended_at": ended.isoformat(),
                "duration_seconds": round(
                    (ended - self.started_at).total_seconds(),
                    3,
                ),
            }
        )
        _write_json(self.metadata_log, metadata)
        footer = (
            "\n"
            "----- Session End -----\n"
            f"Ended   : {ended.isoformat()}\n"
            f"Outcome : {outcome}\n"
        )
        for path in (self.primary_log, self.stdout_log, self.stderr_log):
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(footer)


def create_session_logs(
    root: str | Path,
    *,
    device: str,
    task: str,
    metadata: dict[str, object] | None = None,
    now: datetime | None = None,
) -> SessionLogContext:
    started = now or datetime.now().astimezone()
    root_path = Path(root).expanduser()
    root_path.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S-") + f"{started.microsecond // 1000:03d}"
    base_name = f"{stamp}_{_safe_component(device)}_{_safe_component(task)}"
    directory = _create_unique_directory(root_path, base_name)

    primary_log = directory / f"{_safe_component(task).lower()}.log"
    stdout_log = directory / "openocd.stdout.log"
    stderr_log = directory / "openocd.stderr.log"
    metadata_log = directory / "session.json"
    header = (
        "KeilTool hardware session\n"
        "-------------------------\n"
        f"Started : {started.isoformat()}\n"
        f"Device  : {device}\n"
        f"Task    : {task}\n"
        "-------------------------\n"
    )
    try:
        for path in (primary_log, stdout_log, stderr_log):
            path.write_text(header, encoding="utf-8", newline="\n")
        payload: dict[str, object] = {
            "schema_version": 1,
            "device": device,
            "task": task,
            "started_at": started.isoformat(),
            "outcome": "running",
        }
        payload.update(metadata or {})
        _write_json(metadata_log, payload)
    except Exception:
        for path in (primary_log, stdout_log, stderr_log, metadata_log):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        directory.rmdir()
        raise

    return SessionLogContext(
        directory=directory,
        primary_log=primary_log,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        metadata_log=metadata_log,
        device=device,
        task=task,
        started_at=started,
    )


def _create_unique_directory(root: Path, base_name: str) -> Path:
    for index in range(1, 10_000):
        suffix = "" if index == 1 else f"_{index}"
        candidate = root / f"{base_name}{suffix}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise OSError(f"Unable to create a unique session directory under {root}.")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_component(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in value.strip()
    )
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("._") or "unknown"


__all__ = ["SessionLogContext", "create_session_logs"]
