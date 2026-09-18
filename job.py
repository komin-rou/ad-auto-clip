"""Per-run workspace isolation and durable task status."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class JobExistsError(FileExistsError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_job_name(name: str) -> str:
    candidate = name.strip()
    if not candidate or candidate in {".", ".."}:
        raise ValueError("任务名不能为空")
    if "/" in candidate or "\\" in candidate or ".." in candidate:
        raise ValueError("任务名不能包含路径分隔符或 ..")
    if re.search(r'[<>:"|?*\x00-\x1f]', candidate):
        raise ValueError("任务名包含 Windows 文件名不支持的字符")
    return candidate


def _assert_child(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise ValueError(f"拒绝操作根目录之外的路径：{resolved_path}")


@dataclass(frozen=True)
class JobWorkspace:
    name: str
    temp_dir: Path
    output_dir: Path

    @property
    def status_path(self) -> Path:
        return self.temp_dir / "status.json"

    @property
    def checkpoint_path(self) -> Path:
        return self.temp_dir / "checkpoint.json"

    @classmethod
    def create(cls, config, name: str, overwrite: bool = False) -> "JobWorkspace":
        safe_name = _safe_job_name(name)
        temp_root = Path(config.TEMP_DIR).resolve() / "jobs"
        output_root = Path(config.OUTPUT_ROOT).resolve()
        temp_dir = temp_root / safe_name
        output_dir = output_root / safe_name
        _assert_child(temp_dir, temp_root)
        _assert_child(output_dir, output_root)

        exists = temp_dir.exists() or output_dir.exists()
        if exists and not overwrite:
            raise JobExistsError(
                f"任务“{safe_name}”已存在；测试重跑请添加 --overwrite"
            )
        if overwrite:
            for target, root in ((temp_dir, temp_root), (output_dir, output_root)):
                _assert_child(target, root)
                if target.exists():
                    shutil.rmtree(target)

        temp_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        return cls(safe_name, temp_dir, output_dir)

    @classmethod
    def open_existing(cls, config, name: str) -> "JobWorkspace":
        safe_name = _safe_job_name(name)
        temp_root = Path(config.TEMP_DIR).resolve() / "jobs"
        output_root = Path(config.OUTPUT_ROOT).resolve()
        temp_dir = temp_root / safe_name
        output_dir = output_root / safe_name
        _assert_child(temp_dir, temp_root)
        _assert_child(output_dir, output_root)
        if not temp_dir.is_dir() or not (temp_dir / "status.json").is_file():
            raise FileNotFoundError(f"找不到可续跑任务：{safe_name}")
        output_dir.mkdir(parents=True, exist_ok=True)
        return cls(safe_name, temp_dir, output_dir)

    def remove_zero_byte_artifacts(self) -> list[str]:
        removed: list[str] = []
        for root in (self.temp_dir, self.output_dir):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path != self.status_path and path.stat().st_size == 0:
                    path.unlink()
                    removed.append(str(path))
        return removed


class JobStatus:
    def __init__(self, path: Path, job_name: str):
        self.path = Path(path)
        self.payload = {
            "job": job_name,
            "status": "pending",
            "current_step": None,
            "completed_steps": [],
            "failed_step": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
            "updated_at": _now(),
            "cleanup": {"removed_zero_byte_files": []},
        }
        self._write()

    @classmethod
    def load(cls, path: Path) -> "JobStatus":
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(f"任务状态不存在：{target}")
        instance = cls.__new__(cls)
        instance.path = target
        instance.payload = json.loads(target.read_text(encoding="utf-8"))
        return instance

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.payload["updated_at"] = _now()
        fd, tmp_name = tempfile.mkstemp(
            prefix="status-", suffix=".json.tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def start_step(self, name: str) -> None:
        if self.payload["started_at"] is None:
            self.payload["started_at"] = _now()
        self.payload["status"] = "running"
        self.payload["current_step"] = name
        self.payload["failed_step"] = None
        self.payload["error"] = None
        self._write()

    def complete_step(self, name: str) -> None:
        completed = self.payload["completed_steps"]
        if name not in completed:
            completed.append(name)
        self.payload["current_step"] = None
        self._write()

    def complete(self) -> None:
        self.payload["status"] = "completed"
        self.payload["current_step"] = None
        self.payload["finished_at"] = _now()
        self._write()

    def truncate_from(self, step: str, ordered_steps: list[str]) -> None:
        if step not in ordered_steps:
            raise ValueError(f"未知任务步骤：{step}")
        invalid = set(ordered_steps[ordered_steps.index(step):])
        self.payload["completed_steps"] = [
            name for name in self.payload.get("completed_steps", []) if name not in invalid
        ]
        self.payload["status"] = "pending"
        self.payload["current_step"] = None
        self.payload["failed_step"] = None
        self.payload["error"] = None
        self.payload["finished_at"] = None
        self._write()

    def fail_step(self, name: str, error: BaseException, removed_files: list[str] | None = None) -> None:
        self.payload["status"] = "failed"
        self.payload["current_step"] = None
        self.payload["failed_step"] = name
        self.payload["error"] = f"{type(error).__name__}: {error}"
        self.payload["finished_at"] = _now()
        self.payload["cleanup"]["removed_zero_byte_files"] = removed_files or []
        self._write()


class RunCheckpoint:
    """Atomic JSON storage for a serializable pipeline context."""

    @staticmethod
    def save(payload: dict, path: Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix="checkpoint-", suffix=".json.tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return target

    @staticmethod
    def load(path: Path) -> dict:
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(f"任务检查点不存在：{target}")
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"任务检查点格式错误：{target}")
        return payload
