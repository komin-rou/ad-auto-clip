"""Sequential one-location-per-folder batch execution with durable reports."""
from __future__ import annotations

import csv
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from errors import TransientPipelineError
from location_loader import Location


class TransientBatchError(TransientPipelineError):
    """Backward-compatible batch-specific transient marker."""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class BatchOptions:
    output_root: Path
    jobs_root: Path
    max_retries: int = 2
    resume: bool = False
    overwrite: bool = False
    skip_preflight: bool = False
    retry_delay: float = 0.0

    def __post_init__(self):
        if self.max_retries < 0:
            raise ValueError("max_retries 不能小于 0")
        if self.resume and self.overwrite:
            raise ValueError("批量模式不能同时使用 resume 和 overwrite")


@dataclass(frozen=True)
class BatchItemResult:
    location: str
    row_number: int
    status: str
    attempts: int
    failed_step: str = ""
    error: str = ""
    preview_path: str = ""
    draft_path: str = ""
    updated_at: str = field(default_factory=_now)


@dataclass
class BatchReport:
    items: list[BatchItemResult]
    started_at: str
    finished_at: str

    def as_dict(self) -> dict:
        return {
            "schema_version": 1,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": {
                "total": len(self.items),
                "completed": sum(item.status == "completed" for item in self.items),
                "skipped": sum(item.status == "skipped" for item in self.items),
                "failed": sum(item.status == "failed" for item in self.items),
            },
            "items": [asdict(item) for item in self.items],
        }

    def write_json(self, path: str | Path) -> Path:
        return _atomic_text_write(
            Path(path), json.dumps(self.as_dict(), ensure_ascii=False, indent=2)
        )

    def write_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix="batch-report-", suffix=".csv.tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
                fields = list(BatchItemResult.__dataclass_fields__)
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for item in self.items:
                    writer.writerow(asdict(item))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target


def _atomic_text_write(target: Path, content: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f"{target.stem}-", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def _completed_outputs(location: str, options: BatchOptions) -> tuple[Path, Path] | None:
    status_path = Path(options.jobs_root) / location / "status.json"
    preview = Path(options.output_root) / location / "final_video_with_tts.mp4"
    draft = Path(options.output_root) / location / "jianying_draft" / "editable"
    manifest = draft / "draft_manifest.json"
    if not status_path.is_file():
        return None
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        status.get("status") == "completed"
        and preview.is_file() and preview.stat().st_size > 0
        and manifest.is_file() and manifest.stat().st_size > 0
    ):
        return preview, draft
    return None


def _failure_details(location: str, options: BatchOptions) -> tuple[str, str]:
    status_path = Path(options.jobs_root) / location / "status.json"
    if not status_path.is_file():
        return "", ""
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    return str(payload.get("failed_step") or ""), str(payload.get("error") or "")


def _is_transient(error: BaseException) -> bool:
    if isinstance(error, (ValueError, FileNotFoundError, PermissionError)):
        return False
    if isinstance(error, (TransientPipelineError, TimeoutError, ConnectionError)):
        return True
    name = type(error).__name__.lower()
    return any(token in name for token in ("timeout", "connection", "clienterror"))


def run_batch(
    locations: list[Location],
    pipeline_factory: Callable[[int], object],
    options: BatchOptions,
) -> BatchReport:
    started = _now()
    items: list[BatchItemResult] = []
    for row_number, location in enumerate(locations, start=1):
        name = location.full_name
        if options.resume:
            completed = _completed_outputs(name, options)
            if completed:
                preview, draft = completed
                items.append(BatchItemResult(
                    name, row_number, "skipped", 0,
                    preview_path=str(preview), draft_path=str(draft),
                ))
                continue

        attempts = 0
        while True:
            attempts += 1
            try:
                pipeline = pipeline_factory(row_number)
                status_exists = (
                    Path(options.jobs_root) / name / "status.json"
                ).is_file()
                ctx = pipeline.run(
                    name,
                    overwrite=options.overwrite and attempts == 1,
                    resume=status_exists and (options.resume or attempts > 1),
                    skip_preflight=options.skip_preflight,
                )
                items.append(BatchItemResult(
                    name, row_number, "completed", attempts,
                    preview_path=str(getattr(ctx, "final_output", "")),
                    draft_path=str(getattr(ctx, "jianying_draft_dir", "")),
                ))
                break
            except Exception as exc:
                if _is_transient(exc) and attempts <= options.max_retries:
                    if options.retry_delay > 0:
                        time.sleep(options.retry_delay)
                    continue
                failed_step, status_error = _failure_details(name, options)
                items.append(BatchItemResult(
                    name, row_number, "failed", attempts,
                    failed_step=failed_step,
                    error=status_error or f"{type(exc).__name__}: {exc}",
                ))
                break
    return BatchReport(items=items, started_at=started, finished_at=_now())
