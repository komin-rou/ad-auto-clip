"""Code-defined creative presets shared by editable draft generation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubtitleStylePreset:
    size: float = 6.0
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    alpha: float = 1.0
    border_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    border_width: float = 40.0
    transform_y: float = -0.72
    max_line_width: float = 0.82
    max_lines: int = 2


@dataclass(frozen=True)
class DraftPreset:
    name: str
    width: int
    height: int
    fps: int
    subtitle: SubtitleStylePreset


DEFAULT_PORTRAIT_PRESET = DraftPreset(
    name="portrait_fixed_subtitle_v1",
    width=1080,
    height=1920,
    fps=30,
    subtitle=SubtitleStylePreset(),
)
