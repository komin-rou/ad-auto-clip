"""Detect and cache intervals containing at least one person."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class PersonInterval:
    source: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def merge_person_samples(
    source: str,
    sample_times: list[float],
    person_hits: list[bool],
    sample_period: float,
    merge_gap: float,
    minimum_duration: float,
    source_duration: float | None = None,
) -> list[PersonInterval]:
    if len(sample_times) != len(person_hits):
        raise ValueError("抽帧时间与检测结果数量不一致")
    hit_times = [float(t) for t, hit in zip(sample_times, person_hits) if hit]
    if not hit_times:
        return []
    ranges = []
    start = previous = hit_times[0]
    for current in hit_times[1:]:
        if current - previous > sample_period + merge_gap:
            end = previous + sample_period
            ranges.append((start, min(end, source_duration) if source_duration is not None else end))
            start = current
        previous = current
    end = previous + sample_period
    ranges.append((start, min(end, source_duration) if source_duration is not None else end))
    return [PersonInterval(source, a, b) for a, b in ranges if b - a >= minimum_duration]


def _cache_key(path: Path, model: str, confidence: float, sample_fps: float) -> str:
    stat = path.stat()
    value = f"person-v2|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{model}|{confidence}|{sample_fps}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def detect_person_intervals(
    video_path: str,
    cache_dir: str,
    model_name: str = "yolo11n.pt",
    confidence: float = 0.35,
    sample_fps: float = 2.0,
    merge_gap: float = 0.75,
    minimum_duration: float = 0.5,
    detector: Callable[[object], bool] | None = None,
) -> list[PersonInterval]:
    path = Path(video_path)
    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / f"{_cache_key(path, model_name, confidence, sample_fps)}.json"
    if cache_path.is_file():
        return [PersonInterval(**item) for item in json.loads(cache_path.read_text(encoding="utf-8"))]
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("人物检测需要安装 requirements-vision.txt") from exc
    model = None
    if detector is None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("人物检测需要安装 requirements-vision.txt") from exc
        model = YOLO(model_name)

        def detector(frame):
            result = model.predict(frame, conf=confidence, classes=[0], verbose=False)[0]
            return len(result.boxes) > 0

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频进行人物检测：{path}")
    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / source_fps if frame_count else 0.0
    period = 1.0 / sample_fps
    times, hits = [], []
    current = 0.0
    try:
        while current < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, current * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break
            times.append(current)
            hits.append(bool(detector(frame)))
            current += period
    finally:
        capture.release()
    intervals = merge_person_samples(
        str(path), times, hits, period, merge_gap, minimum_duration,
        source_duration=duration,
    )
    cache_path.write_text(json.dumps([asdict(x) for x in intervals], ensure_ascii=False, indent=2), encoding="utf-8")
    return intervals
