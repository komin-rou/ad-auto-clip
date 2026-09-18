"""Plan a narration-length timeline from non-reusable person intervals."""
from __future__ import annotations

from dataclasses import dataclass

from person_detector import PersonInterval


class InsufficientPersonFootage(ValueError):
    def __init__(self, shortage_seconds: float, available_seconds: float, required_seconds: float):
        self.shortage_seconds = shortage_seconds
        self.available_seconds = available_seconds
        self.required_seconds = required_seconds
        super().__init__(
            f"人物素材不足：1.0 倍速仍缺少 {shortage_seconds:.2f} 秒"
            f"（可用 {available_seconds:.2f} 秒，需要 {required_seconds:.2f} 秒）"
        )


@dataclass(frozen=True)
class ClipPlanItem:
    source: str
    source_start: float
    source_end: float
    speed: float
    output_duration: float

    @property
    def source_duration(self) -> float:
        return self.source_end - self.source_start


@dataclass(frozen=True)
class ClipPlan:
    speed: float
    narration_duration: float
    available_source_duration: float
    items: tuple[ClipPlanItem, ...]

    @property
    def output_duration(self) -> float:
        return sum(item.output_duration for item in self.items)


def plan_person_timeline(
    intervals: list[PersonInterval],
    narration_duration: float,
    preferred_speed: float = 2.0,
    minimum_speed: float = 1.0,
) -> ClipPlan:
    if narration_duration <= 0:
        raise ValueError("旁白时长必须大于 0")
    if not 0 < minimum_speed <= preferred_speed:
        raise ValueError("倍速范围无效")
    available = sum(max(0.0, interval.duration) for interval in intervals)
    required_at_minimum = narration_duration * minimum_speed
    if available + 1e-9 < required_at_minimum:
        shortage = required_at_minimum - available
        raise InsufficientPersonFootage(shortage, available, required_at_minimum)
    speed = min(preferred_speed, available / narration_duration)
    speed = max(minimum_speed, speed)
    required_source = narration_duration * speed
    remaining = required_source
    items = []
    for interval in intervals:
        if remaining <= 1e-9:
            break
        take = min(interval.duration, remaining)
        if take <= 0:
            continue
        output_duration = take / speed
        items.append(ClipPlanItem(interval.source, interval.start, interval.start + take, speed, output_duration))
        remaining -= take
    if remaining > 1e-6:
        raise RuntimeError("剪辑规划内部错误：人物区间未能覆盖计划")
    if items:
        drift = narration_duration - sum(x.output_duration for x in items)
        if abs(drift) > 1e-9:
            last = items[-1]
            corrected_output = last.output_duration + drift
            corrected_end = last.source_start + corrected_output * speed
            items[-1] = ClipPlanItem(last.source, last.source_start, corrected_end, speed, corrected_output)
    return ClipPlan(speed, narration_duration, available, tuple(items))
