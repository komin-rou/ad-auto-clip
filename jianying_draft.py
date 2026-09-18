"""Build and validate editable Jianying drafts from a rendered clip plan."""
from __future__ import annotations

import importlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clip_planner import ClipPlan
from style_presets import DraftPreset, SubtitleStylePreset


class JianyingDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class DraftVideoItem:
    source: str
    source_start: float
    source_duration: float
    target_start: float
    output_duration: float
    speed: float
    volume: float = 0.0


@dataclass(frozen=True)
class DraftAudioItem:
    source: str
    target_start: float
    duration: float
    volume: float = 1.0


@dataclass(frozen=True)
class DraftDedupItem:
    source: str
    alpha: float
    mix_mode: str = "叠加"


@dataclass(frozen=True)
class DraftStickerItem:
    source: str
    transform_x: float
    transform_y: float
    scale: float
    alpha: float


@dataclass(frozen=True)
class DraftFilterItem:
    source_name: str
    jianying_filter: str
    intensity: float


@dataclass(frozen=True)
class DraftBlueprint:
    name: str
    width: int
    height: int
    fps: int
    duration: float
    video_items: tuple[DraftVideoItem, ...]
    narration: DraftAudioItem
    srt_path: str
    subtitle_style: SubtitleStylePreset
    preset_name: str
    dedup_layers: tuple[DraftDedupItem, ...] = ()
    stickers: tuple[DraftStickerItem, ...] = ()
    filters: tuple[DraftFilterItem, ...] = ()


_FILTER_NAME_MAP = {
    "01_暖色调": "日落橘",
    "02_冷色调": "冷蓝",
    "03_复古怀旧": "旧时代I",
    "04_电影感": "情感电影",
    "05_高对比度": "亢奋",
    "06_日系清新": "日系奶油",
    "08_鲜艳饱和": "彩果",
    "09_暗角": "敦刻尔克",
    "10_柔焦": "奶油",
    "11_通透提亮": "净白肤",
    "12_冷白皮": "冷白",
}


def _jianying_filter_name(source_name: str) -> str:
    stem = Path(source_name).stem
    normalized = stem.removeprefix("filter_")
    try:
        return _FILTER_NAME_MAP[normalized]
    except KeyError as exc:
        raise ValueError(f"未配置剪映滤镜映射：{source_name}") from exc


def _sticker_positions(count: int) -> tuple[tuple[float, float], ...]:
    corners = ((-0.9, 0.9), (0.9, 0.9), (-0.9, -0.9), (0.9, -0.9))
    if count > len(corners):
        raise ValueError("可编辑剪映草稿最多支持 4 个四角贴纸")
    return corners[:count]


@dataclass(frozen=True)
class DraftResult:
    draft_dir: Path
    manifest_path: Path


@dataclass(frozen=True)
class CompatibilityReport:
    passed: bool
    status: str
    draft_dir: str
    issues: tuple[str, ...]
    canvas: dict
    track_counts: dict
    manual_open_confirmed: bool = False
    jianying_version: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def build_draft_blueprint(
    name: str,
    clip_plan: ClipPlan,
    narration_path: str,
    srt_path: str,
    preset: DraftPreset,
    *,
    dedup_paths: list[str] | tuple[str, ...] = (),
    dedup_alpha: float = 0.03,
    sticker_paths: list[str] | tuple[str, ...] = (),
    selected_filters: list[tuple[str, str]] | tuple[tuple[str, str], ...] = (),
    sticker_scale: float = 0.05,
    sticker_alpha: float = 0.08,
    filter_intensity: float = 2.0,
) -> DraftBlueprint:
    if not clip_plan.items:
        raise ValueError("剪映草稿不能使用空剪辑计划")
    if clip_plan.narration_duration <= 0:
        raise ValueError("剪映草稿旁白时长必须大于 0")
    if not 0 <= dedup_alpha <= 1:
        raise ValueError("剪映去重图层透明度必须在 0 到 1 之间")
    if not 0 < sticker_scale <= 1:
        raise ValueError("剪映贴纸缩放比例必须在 0 到 1 之间")
    if not 0 <= sticker_alpha <= 1:
        raise ValueError("剪映贴纸透明度必须在 0 到 1 之间")
    if not 0 <= filter_intensity <= 100:
        raise ValueError("剪映滤镜强度必须在 0 到 100 之间")
    target_start = 0.0
    video_items = []
    for item in clip_plan.items:
        video_items.append(DraftVideoItem(
            source=str(Path(item.source).resolve()),
            source_start=item.source_start,
            source_duration=item.source_duration,
            target_start=target_start,
            output_duration=item.output_duration,
            speed=item.speed,
        ))
        target_start += item.output_duration
    if abs(target_start - clip_plan.narration_duration) > 0.15:
        raise ValueError(
            f"剪辑计划与旁白时长不一致：画面 {target_start:.2f} 秒，"
            f"旁白 {clip_plan.narration_duration:.2f} 秒"
        )
    return DraftBlueprint(
        name=name,
        width=preset.width,
        height=preset.height,
        fps=preset.fps,
        duration=clip_plan.narration_duration,
        video_items=tuple(video_items),
        narration=DraftAudioItem(
            source=str(Path(narration_path).resolve()),
            target_start=0.0,
            duration=clip_plan.narration_duration,
        ),
        srt_path=str(Path(srt_path).resolve()),
        subtitle_style=preset.subtitle,
        preset_name=preset.name,
        dedup_layers=tuple(
            DraftDedupItem(source=str(Path(path).resolve()), alpha=dedup_alpha)
            for path in dedup_paths
        ),
        stickers=tuple(
            DraftStickerItem(
                source=str(Path(path).resolve()),
                transform_x=position[0],
                transform_y=position[1],
                scale=sticker_scale,
                alpha=sticker_alpha,
            )
            for path, position in zip(sticker_paths, _sticker_positions(len(sticker_paths)))
        ),
        filters=tuple(
            DraftFilterItem(
                source_name=name,
                jianying_filter=_jianying_filter_name(name),
                intensity=filter_intensity,
            )
            for name, _parameters in selected_filters
        ),
    )


def _seconds_range(module: Any, start: float, duration: float):
    return module.trange(f"{start:.6f}s", f"{duration:.6f}s")


def _load_draft_module():
    try:
        return importlib.import_module("pyJianYingDraft")
    except (ImportError, OSError) as exc:
        raise JianyingDependencyError(
            "无法加载 pyJianYingDraft；请先执行 "
            "pip install -r requirements-jianying.txt"
        ) from exc


def _require_inputs(blueprint: DraftBlueprint) -> None:
    missing = []
    for item in blueprint.video_items:
        if not Path(item.source).is_file():
            missing.append(item.source)
    for path in (blueprint.narration.source, blueprint.srt_path):
        if not Path(path).is_file():
            missing.append(path)
    for layer in blueprint.dedup_layers:
        if not Path(layer.source).is_file():
            missing.append(layer.source)
    for sticker in blueprint.stickers:
        if not Path(sticker.source).is_file():
            missing.append(sticker.source)
    if missing:
        raise FileNotFoundError("剪映草稿素材不存在：" + "、".join(missing))


@contextmanager
def _disable_automatic_jianying_registration():
    """Prevent the library from discovering and mutating Jianying User Data."""
    missing = object()
    previous = os.environ.pop("LOCALAPPDATA", missing)
    try:
        yield
    finally:
        if previous is not missing:
            os.environ["LOCALAPPDATA"] = previous


def _populate_and_save_draft(module, blueprint: DraftBlueprint, root: Path, draft_name: str) -> None:
    folder = module.DraftFolder(str(root))
    script = folder.create_draft(
        draft_name, blueprint.width, blueprint.height, blueprint.fps,
        allow_replace=True,
    )
    track_specs = [
        module.TrackSpec(module.TrackType.audio, "narration"),
        module.TrackSpec(module.TrackType.video, "main_video"),
    ]
    track_specs.extend(
        module.TrackSpec(module.TrackType.video, f"dedup_{index}")
        for index, _layer in enumerate(blueprint.dedup_layers)
    )
    track_specs.append(module.TrackSpec(module.TrackType.text, "captions"))
    track_specs.extend(
        module.TrackSpec(module.TrackType.video, f"sticker_{index}")
        for index, _sticker in enumerate(blueprint.stickers)
    )
    track_specs.extend(
        module.TrackSpec(module.TrackType.filter, f"filter_{index}")
        for index, _filter in enumerate(blueprint.filters)
    )
    track_refs = script.append_tracks(track_specs)
    narration_ref, video_ref = track_refs[:2]
    dedup_end = 2 + len(blueprint.dedup_layers)
    dedup_refs = track_refs[2:dedup_end]
    sticker_start = dedup_end + 1
    sticker_refs = track_refs[sticker_start:sticker_start + len(blueprint.stickers)]
    for item in blueprint.video_items:
        segment = module.VideoSegment(
            item.source,
            _seconds_range(module, item.target_start, item.output_duration),
            source_timerange=_seconds_range(
                module, item.source_start, item.source_duration
            ),
            speed=item.speed,
            volume=item.volume,
        )
        script.add_segment(segment, track=video_ref)

    full_range = _seconds_range(module, 0.0, blueprint.duration)
    for layer, track_ref in zip(blueprint.dedup_layers, dedup_refs):
        segment = module.VideoSegment(
            layer.source,
            full_range,
            volume=0.0,
            clip_settings=module.ClipSettings(alpha=layer.alpha),
        )
        try:
            mix_mode = getattr(module.MixModeType, layer.mix_mode)
        except AttributeError as exc:
            raise JianyingDependencyError(
                f"pyJianYingDraft 缺少剪映混合模式：{layer.mix_mode}"
            ) from exc
        segment.set_mix_mode(mix_mode)
        script.add_segment(segment, track=track_ref)

    for sticker, track_ref in zip(blueprint.stickers, sticker_refs):
        segment = module.VideoSegment(
            sticker.source,
            full_range,
            volume=0.0,
            clip_settings=module.ClipSettings(
                alpha=sticker.alpha,
                scale_x=sticker.scale,
                scale_y=sticker.scale,
                transform_x=sticker.transform_x,
                transform_y=sticker.transform_y,
            ),
        )
        script.add_segment(segment, track=track_ref)

    for index, filter_item in enumerate(blueprint.filters):
        try:
            filter_type = getattr(module.FilterType, filter_item.jianying_filter)
        except AttributeError as exc:
            raise JianyingDependencyError(
                f"pyJianYingDraft 缺少剪映滤镜：{filter_item.jianying_filter}"
            ) from exc
        script.add_filter(
            filter_type,
            full_range,
            track_name=f"filter_{index}",
            intensity=filter_item.intensity,
        )
    narration = module.AudioSegment(
        blueprint.narration.source,
        _seconds_range(
            module, blueprint.narration.target_start, blueprint.narration.duration
        ),
        volume=blueprint.narration.volume,
    )
    script.add_segment(narration, track=narration_ref)

    style = blueprint.subtitle_style
    style_reference = module.TextSegment(
        "字幕样式",
        _seconds_range(module, 0.0, min(1.0, blueprint.duration)),
        style=module.TextStyle(
            size=style.size,
            color=style.color,
            alpha=style.alpha,
            align=1,
            auto_wrapping=True,
            max_line_width=style.max_line_width,
        ),
        border=module.TextBorder(
            alpha=1.0, color=style.border_color, width=style.border_width
        ),
        clip_settings=module.ClipSettings(transform_y=style.transform_y),
    )
    script.import_srt(
        blueprint.srt_path,
        track_name="captions",
        style_reference=style_reference,
        clip_settings=None,
    )
    script.save()


def generate_jianying_draft(
    blueprint: DraftBlueprint,
    output_root: str | Path,
    *,
    draft_module=None,
) -> DraftResult:
    _require_inputs(blueprint)
    module = draft_module or _load_draft_module()
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    draft_name = "editable"
    with _disable_automatic_jianying_registration():
        _populate_and_save_draft(module, blueprint, root, draft_name)

    draft_dir = root / draft_name
    manifest_path = draft_dir / "draft_manifest.json"
    manifest = {
        "schema_version": 1,
        "generator": "pyJianYingDraft",
        "preset": blueprint.preset_name,
        "canvas": {
            "width": blueprint.width,
            "height": blueprint.height,
            "fps": blueprint.fps,
        },
        "duration": blueprint.duration,
        "track_counts": {
            "video": len(blueprint.video_items),
            "audio": 1,
            "text": 1,
            "dedup": len(blueprint.dedup_layers),
            "sticker": len(blueprint.stickers),
            "filter": len(blueprint.filters),
        },
        "video_items": [asdict(item) for item in blueprint.video_items],
        "narration": asdict(blueprint.narration),
        "srt_path": blueprint.srt_path,
        "subtitle_style": asdict(blueprint.subtitle_style),
        "dedup_layers": [asdict(item) for item in blueprint.dedup_layers],
        "stickers": [asdict(item) for item in blueprint.stickers],
        "filters": [asdict(item) for item in blueprint.filters],
        "compatibility": "structure_generated_manual_open_pending",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return DraftResult(draft_dir=draft_dir, manifest_path=manifest_path)


def validate_draft_structure(
    draft_dir: str | Path,
    *,
    manual_open_confirmed: bool = False,
    jianying_version: str = "",
) -> CompatibilityReport:
    if manual_open_confirmed and not jianying_version.strip():
        raise ValueError("确认手工打开剪映草稿时必须提供剪映版本")
    root = Path(draft_dir)
    issues: list[str] = []
    for required in ("draft_content.json", "draft_meta_info.json", "draft_manifest.json"):
        path = root / required
        if not path.is_file() or path.stat().st_size == 0:
            issues.append(f"缺少草稿文件：{required}")
    def read_object(name: str, label: str) -> dict:
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"{label}不可读：{exc}")
            return {}
        if not isinstance(payload, dict):
            issues.append(f"{label}顶层必须是对象")
            return {}
        return payload

    manifest = read_object("draft_manifest.json", "草稿清单")
    native_content = read_object("draft_content.json", "原生草稿内容")
    native_meta = read_object("draft_meta_info.json", "原生草稿元数据")

    canvas = manifest.get("canvas", {})
    expected_canvas = {"width": 1080, "height": 1920, "fps": 30}
    if canvas != expected_canvas:
        issues.append(f"画布配置不正确：{canvas}")
    counts = manifest.get("track_counts", {})
    if not isinstance(counts, dict):
        issues.append("轨道数量格式错误：track_counts 必须是对象")
        counts = {}
    for name in ("video", "audio", "text", "dedup", "sticker", "filter"):
        try:
            count = int(counts.get(name, 0))
        except (TypeError, ValueError):
            issues.append(f"轨道数量格式错误：{name}={counts.get(name)!r}")
            count = 0
        if name in ("video", "audio", "text") and count < 1:
            issues.append(f"缺少{name}轨道")

    native_canvas = native_content.get("canvas_config")
    native_fps = native_content.get("fps")
    if not isinstance(native_canvas, dict) or (
        native_canvas.get("width"), native_canvas.get("height"), native_fps
    ) != (1080, 1920, 30):
        issues.append(f"原生草稿画布配置不正确：{native_canvas}，fps={native_fps}")

    native_tracks = native_content.get("tracks")
    native_counts = {
        "video": 0, "audio": 0, "text": 0,
        "dedup": 0, "sticker": 0, "filter": 0,
    }
    if isinstance(native_tracks, list):
        for track in native_tracks:
            if not isinstance(track, dict):
                continue
            track_type = track.get("type")
            segments = track.get("segments")
            if not isinstance(segments, list) or not segments:
                continue
            if track_type in ("video", "audio", "text"):
                native_counts[track_type] += 1
            track_name = str(track.get("name", ""))
            if track_type == "video" and track_name.startswith("dedup_"):
                native_counts["dedup"] += 1
            if track_type == "video" and track_name.startswith("sticker_"):
                native_counts["sticker"] += 1
            if track_type == "filter":
                native_counts["filter"] += 1
    for name in ("video", "audio", "text"):
        count = native_counts[name]
        if count < 1:
            issues.append(f"原生草稿轨道缺失或为空：{name}")
    for name, label in (("dedup", "去重"), ("sticker", "贴纸"), ("filter", "滤镜")):
        expected = int(counts.get(name, 0) or 0)
        if native_counts[name] < expected:
            issues.append(
                f"原生{label}轨道数量不足："
                f"期望 {expected}，实际 {native_counts[name]}"
            )

    native_duration_raw = native_content.get("duration")
    try:
        native_duration = float(native_duration_raw) / 1_000_000
    except (TypeError, ValueError):
        native_duration = 0.0
    narration = manifest.get("narration", {})
    if not isinstance(narration, dict):
        issues.append("旁白清单格式错误：narration 必须是对象")
        narration = {}
    narration_duration = narration.get("duration")
    manifest_duration = manifest.get("duration")
    try:
        narration_duration = float(narration_duration)
        manifest_duration = float(manifest_duration)
    except (TypeError, ValueError):
        narration_duration = manifest_duration = 0.0
    if native_duration <= 0:
        issues.append(f"原生草稿时长无效：{native_duration_raw}")
    elif (
        abs(native_duration - narration_duration) > 0.15
        or abs(native_duration - manifest_duration) > 0.15
    ):
        issues.append(
            f"原生草稿时长与旁白不一致：草稿 {native_duration:.3f} 秒，"
            f"旁白 {narration_duration:.3f} 秒"
        )

    if not native_meta.get("draft_id"):
        issues.append("原生草稿元数据缺少 draft_id")

    native_materials = native_content.get("materials", {})
    if not isinstance(native_materials, dict):
        issues.append("原生草稿素材表格式错误")
        native_materials = {}
    for group in ("videos", "audios"):
        entries = native_materials.get(group, [])
        if not isinstance(entries, list) or not entries:
            issues.append(f"原生草稿素材表缺少：{group}")
            continue
        for entry in entries:
            source = entry.get("path", "") if isinstance(entry, dict) else ""
            if not isinstance(source, (str, os.PathLike)):
                issues.append(f"原生草稿素材路径格式错误：{source!r}")
                continue
            if not os.fspath(source) or not Path(source).is_file():
                issues.append(f"原生草稿素材不存在：{source or '<empty>'}")
    video_items = manifest.get("video_items", [])
    if not isinstance(video_items, list):
        issues.append("视频素材清单格式错误：video_items 必须是数组")
        video_items = []
    material_paths = []
    for item in video_items:
        if not isinstance(item, dict):
            issues.append("视频素材清单格式错误：条目必须是对象")
            continue
        material_paths.append(item.get("source", ""))
    material_paths.extend([
        narration.get("source", ""),
        manifest.get("srt_path", ""),
    ])
    dedup_layers = manifest.get("dedup_layers", [])
    if not isinstance(dedup_layers, list):
        issues.append("去重素材清单格式错误：dedup_layers 必须是数组")
        dedup_layers = []
    for layer in dedup_layers:
        if not isinstance(layer, dict):
            issues.append("去重素材清单格式错误：条目必须是对象")
            continue
        material_paths.append(layer.get("source", ""))
    stickers = manifest.get("stickers", [])
    if not isinstance(stickers, list):
        issues.append("贴纸素材清单格式错误：stickers 必须是数组")
        stickers = []
    for sticker in stickers:
        if not isinstance(sticker, dict):
            issues.append("贴纸素材清单格式错误：条目必须是对象")
            continue
        material_paths.append(sticker.get("source", ""))
    for source in material_paths:
        if not isinstance(source, (str, os.PathLike)):
            issues.append(f"素材路径格式错误：{source!r}")
            continue
        if not os.fspath(source):
            issues.append("素材路径格式错误：路径不能为空")
            continue
        if not Path(source).is_file():
            issues.append(f"素材不存在：{source}")
    passed = not issues
    if not passed:
        status = "structure_failed"
    elif manual_open_confirmed:
        normalized_version = jianying_version.strip().replace(".", "_")
        status = f"verified_jianying_{normalized_version}"
    else:
        status = "structure_passed_manual_open_pending"
    return CompatibilityReport(
        passed=passed,
        status=status,
        draft_dir=str(root.resolve()),
        issues=tuple(issues),
        canvas=canvas,
        track_counts=counts,
        manual_open_confirmed=manual_open_confirmed and passed,
        jianying_version=jianying_version.strip() if manual_open_confirmed and passed else "",
    )


def write_compatibility_report(
    report: CompatibilityReport, path: str | Path
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target
