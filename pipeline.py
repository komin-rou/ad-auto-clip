"""
主流程编排模块
VideoPipeline 类按顺序执行所有步骤，RunContext 在步骤间传递状态
"""
import os
import re
import time
import asyncio
import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Tuple

from config import config
from logger import logger
from utils import (
    run_ffmpeg,
    get_target_files,
    get_audio_duration,
    validate_runtime,
)
from libraries import (
    pick_random_voice,
    pick_random_font,
    load_random_filters,
    pick_random_stickers,
)
from tts import SpeechBoundary, generate_tts_result
from subtitle import (
    generate_srt_from_boundaries,
    move_subtitle_down,
    optimize_srt_layout,
    read_subtitle_filter_param,
    set_subtitle_font_size,
)
from deepseek_subtitle import segment_caption_deepseek
from video_processor import render_timeline, slice_dedup_videos
from effects import build_final_filter_complex
from output_manager import write_params_record
from job import JobStatus, JobWorkspace, RunCheckpoint
from location_loader import Location, load_location
from copywriter import AdScript, FactLibrary, generate_ad_script
from person_detector import PersonInterval, detect_person_intervals
from clip_planner import ClipPlan, ClipPlanItem, plan_person_timeline
from utils import probe_media, probe_media_cached
from jianying_draft import (
    build_draft_blueprint,
    generate_jianying_draft,
    validate_draft_structure,
    write_compatibility_report,
)
from style_presets import DEFAULT_PORTRAIT_PRESET


def build_final_composite_command(
    input_cmds: list[str],
    filter_complex: str,
    encode_args: list[str],
    output_path: str,
    narration_duration: float,
) -> list[str]:
    """Build a composite command whose muxed output cannot outlive narration."""
    return input_cmds + [
        "-filter_complex", filter_complex,
        "-map", "[out_video]",
        "-map", "1:a",
        *encode_args,
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-t", f"{narration_duration:.6f}",
        output_path,
    ]


@dataclass
class RunContext:
    """运行上下文，在各步骤间传递状态"""
    output_name: str
    workspace: JobWorkspace
    run_params: dict = field(default_factory=dict)
    # TTS相关
    tts_text: str = ""
    tts_audio_path: str = ""
    tts_duration: float = 0.0
    selected_voice: str = ""
    voice_desc: str = ""
    location: Location | None = None
    ad_script: AdScript | None = None
    speech_boundaries: List[SpeechBoundary] = field(default_factory=list)
    timing_source: str = ""
    # 字幕相关
    srt_path: str = ""
    subtitle_filter: str = ""
    random_font: str = ""
    # 视频处理相关
    per_clip_duration: float = 0.0
    speed_temp_clips: List[str] = field(default_factory=list)
    base_merged: str = ""
    person_intervals: List[PersonInterval] = field(default_factory=list)
    clip_plan: ClipPlan | None = None
    # 去重相关
    dedup_clips: List[str] = field(default_factory=list)
    num_layers: int = 0
    # 特效相关
    selected_filters: List[Tuple[str, str]] = field(default_factory=list)
    use_stickers: List[str] = field(default_factory=list)
    # 输出
    final_output: str = ""
    jianying_draft_dir: str = ""
    jianying_manifest_path: str = ""
    compatibility_report_path: str = ""
    input_fingerprints: dict[str, str] = field(default_factory=dict)

    def to_checkpoint(self) -> dict:
        return {
            "schema_version": 2,
            "output_name": self.output_name,
            "run_params": self.run_params,
            "tts_text": self.tts_text,
            "tts_audio_path": self.tts_audio_path,
            "tts_duration": self.tts_duration,
            "selected_voice": self.selected_voice,
            "voice_desc": self.voice_desc,
            "location": asdict(self.location) if self.location else None,
            "ad_script": asdict(self.ad_script) if self.ad_script else None,
            "speech_boundaries": [asdict(item) for item in self.speech_boundaries],
            "timing_source": self.timing_source,
            "srt_path": self.srt_path,
            "subtitle_filter": self.subtitle_filter,
            "random_font": self.random_font,
            "base_merged": self.base_merged,
            "person_intervals": [asdict(item) for item in self.person_intervals],
            "clip_plan": None if self.clip_plan is None else {
                "speed": self.clip_plan.speed,
                "narration_duration": self.clip_plan.narration_duration,
                "available_source_duration": self.clip_plan.available_source_duration,
                "items": [asdict(item) for item in self.clip_plan.items],
            },
            "dedup_clips": self.dedup_clips,
            "num_layers": self.num_layers,
            "selected_filters": self.selected_filters,
            "use_stickers": self.use_stickers,
            "final_output": self.final_output,
            "jianying_draft_dir": self.jianying_draft_dir,
            "jianying_manifest_path": self.jianying_manifest_path,
            "compatibility_report_path": self.compatibility_report_path,
            "input_fingerprints": self.input_fingerprints,
        }

    @classmethod
    def from_checkpoint(cls, payload: dict, workspace: JobWorkspace) -> "RunContext":
        ctx = cls(output_name=payload.get("output_name", workspace.name), workspace=workspace)
        scalar_fields = (
            "run_params", "tts_text", "tts_audio_path", "tts_duration", "selected_voice",
            "voice_desc", "timing_source", "srt_path", "subtitle_filter", "random_font",
            "base_merged", "dedup_clips", "num_layers", "selected_filters", "use_stickers",
            "final_output", "jianying_draft_dir", "jianying_manifest_path",
            "compatibility_report_path",
            "input_fingerprints",
        )
        for name in scalar_fields:
            if name in payload:
                setattr(ctx, name, payload[name])
        if payload.get("location"):
            ctx.location = Location(**payload["location"])
        if payload.get("ad_script"):
            ctx.ad_script = AdScript(**payload["ad_script"])
        ctx.speech_boundaries = [
            SpeechBoundary(**item) for item in payload.get("speech_boundaries", [])
        ]
        ctx.person_intervals = [
            PersonInterval(**item) for item in payload.get("person_intervals", [])
        ]
        plan = payload.get("clip_plan")
        if plan:
            ctx.clip_plan = ClipPlan(
                speed=float(plan["speed"]),
                narration_duration=float(plan["narration_duration"]),
                available_source_duration=float(plan["available_source_duration"]),
                items=tuple(ClipPlanItem(**item) for item in plan.get("items", [])),
            )
        ctx.selected_filters = [tuple(item) for item in ctx.selected_filters]
        return ctx


class VideoPipeline:
    """广告视频自动化混剪主流程"""

    STEP_METHODS = (
        ("content", "_step_content"),
        ("tts", "_step_tts"),
        ("subtitle", "_step_subtitle"),
        ("person_detection", "_step_person_detection"),
        ("clip_plan", "_step_clip_plan"),
        ("timeline_render", "_step_timeline_render"),
        ("effects_prepare", "_step5_dedup"),
        ("composite", "_step6_effects_and_composite"),
        ("jianying_draft", "_step_jianying_draft"),
        ("record", "_step7_write_record"),
    )

    @staticmethod
    def _fingerprint_path(value: str | Path) -> str:
        path = Path(value)
        digest = hashlib.sha256()
        if not path.exists():
            return "missing"
        files = [path] if path.is_file() else sorted(
            (item for item in path.rglob("*") if item.is_file()),
            key=lambda item: str(item.relative_to(path)).casefold(),
        )
        for item in files:
            relative = item.name if path.is_file() else str(item.relative_to(path))
            digest.update(relative.encode("utf-8", errors="surrogatepass"))
            with item.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fingerprint_payload(payload) -> str:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _input_fingerprints(self) -> dict[str, str]:
        path_fingerprint = self._fingerprint_path
        make = self._fingerprint_payload
        return {
            "content": make({
                "locations": path_fingerprint(config.LOCATIONS_FILE),
                "facts": path_fingerprint(config.FACTS_FILE),
                "row": config.LOCATION_ROW,
                "script": config.SUPPLIED_SCRIPT,
                "model": config.DEEPSEEK_MODEL,
                "base_url": config.DEEPSEEK_BASE_URL,
                "api_key_available": bool(config.DEEPSEEK_API_KEY),
                "target_chars": config.COPY_TARGET_CHARS,
            }),
            "tts": make({
                "provider": config.TTS_PROVIDER,
                "voice": config.TTS_VOICE,
                "rate": config.TTS_RATE,
                "volume": config.TTS_VOLUME,
                "voices": path_fingerprint(config.VOICE_LIB_FILE),
            }),
            "subtitle": make({
                "mode": config.SUBTITLE_MODE,
                "model": config.DEEPSEEK_MODEL,
                "base_url": config.DEEPSEEK_BASE_URL,
                "api_key_available": bool(config.DEEPSEEK_API_KEY),
                "max_chars": config.SUBTITLE_MAX_CHARS_PER_LINE,
                "down": config.SUBTITLE_DOWN_RATIO,
                "font_size": config.SUBTITLE_FONT_SIZE,
                "params": path_fingerprint(Path(config.SUBTITLE_DIR) / config.SUBTITLE_PARAM_FILE),
            }),
            "person_detection": make({
                "raw_clips": path_fingerprint(config.RAW_VIDEO_DIR),
                "enabled": config.PERSON_DETECTION_ENABLED,
                "model": config.PERSON_MODEL,
                "model_file": path_fingerprint(
                    Path(config.PERSON_MODEL) if Path(config.PERSON_MODEL).is_absolute()
                    else Path(config.BASE_DIR) / config.PERSON_MODEL
                ),
                "confidence": config.PERSON_CONFIDENCE,
                "sample_fps": config.PERSON_SAMPLE_FPS,
                "gap": config.PERSON_INTERVAL_GAP,
                "minimum": config.PERSON_MIN_INTERVAL,
            }),
            "clip_plan": make({
                "preferred_speed": config.PREFERRED_SPEED,
                "minimum_speed": config.MINIMUM_SPEED,
            }),
            "timeline_render": make({
                "resolution": config.TARGET_RESOLUTION,
                "fps": config.TARGET_FPS,
                "encoder": config.get_video_encode_args(),
            }),
            "effects_prepare": make({
                "dedup": path_fingerprint(config.DEDUP_DIR),
                "stickers": path_fingerprint(config.STICKER_DIR),
                "filters": path_fingerprint(config.FILTER_LIB_DIR),
                "fonts": path_fingerprint(config.FONT_LIB_DIR),
                "sticker_count": config.STICKER_COUNT,
                "dedup_alpha": config.DEDUP_ALPHA,
            }),
            "composite": make({
                "sticker_alpha": config.STICKER_ALPHA,
                "sticker_scale": config.STICKER_SCALE,
                "filter_count": config.NUM_RANDOM_FILTERS,
                "filter_opacity": config.FILTER_BLEND_OPACITY,
            }),
            "jianying_draft": make({
                "enabled": config.JIANYING_DRAFT_ENABLED,
                "name": config.JIANYING_DRAFT_NAME,
                "preset": asdict(DEFAULT_PORTRAIT_PRESET),
                "sticker_scale": config.STICKER_SCALE,
                "sticker_alpha": config.STICKER_ALPHA,
                "dedup_alpha": config.DEDUP_ALPHA,
                "filter_intensity": config.FILTER_BLEND_OPACITY * 100,
            }),
            "record": make({"schema": 1}),
        }

    def run(
        self,
        output_name: str,
        overwrite: bool = False,
        resume: bool = False,
        skip_preflight: bool = False,
    ) -> RunContext:
        """
        执行完整的视频生成流程
        :param output_name: 输出子目录名
        :return: RunContext 运行上下文
        """
        if not skip_preflight:
            validate_runtime(config)

        if overwrite and resume:
            raise ValueError("--overwrite 与 --resume 不能同时使用")
        if resume:
            workspace = JobWorkspace.open_existing(config, output_name)
            status = JobStatus.load(workspace.status_path)
            if workspace.checkpoint_path.is_file():
                ctx = RunContext.from_checkpoint(
                    RunCheckpoint.load(workspace.checkpoint_path), workspace
                )
            else:
                ctx = RunContext(output_name=workspace.name, workspace=workspace)
                status.truncate_from(
                    self.STEP_METHODS[0][0], [name for name, _ in self.STEP_METHODS]
                )
        else:
            workspace = JobWorkspace.create(config, output_name, overwrite=overwrite)
            status = JobStatus(workspace.status_path, workspace.name)
            ctx = RunContext(output_name=workspace.name, workspace=workspace)
            ctx.run_params["输出目录"] = output_name
            ctx.run_params["运行时间"] = time.strftime("%Y-%m-%d %H:%M:%S")

        ordered_steps = [name for name, _ in self.STEP_METHODS]
        completed = list(status.payload.get("completed_steps", []))
        current_fingerprints = self._input_fingerprints()
        stored_fingerprints = dict(ctx.input_fingerprints)
        if resume:
            for name in ordered_steps:
                if name not in completed:
                    break
                if stored_fingerprints.get(name) != current_fingerprints.get(name):
                    logger.info("断点续跑：输入变化，从步骤 %s 重新执行", name)
                    status.truncate_from(name, ordered_steps)
                    completed = list(status.payload.get("completed_steps", []))
                    break
        ctx.input_fingerprints = current_fingerprints
        for name in ordered_steps:
            if name not in completed:
                break
            if not self._is_step_artifact_valid(name, ctx):
                status.truncate_from(name, ordered_steps)
                completed = list(status.payload.get("completed_steps", []))
                break

        current_step = "bootstrap"
        try:
            for current_step, _ in self.STEP_METHODS:
                if current_step in completed:
                    logger.info("断点续跑：跳过已完成步骤 %s", current_step)
                    continue
                status.start_step(current_step)
                self._run_named_step(current_step, ctx)
                status.complete_step(current_step)
                RunCheckpoint.save(ctx.to_checkpoint(), workspace.checkpoint_path)
            status.complete()
            return ctx
        except BaseException as exc:
            RunCheckpoint.save(ctx.to_checkpoint(), workspace.checkpoint_path)
            removed = workspace.remove_zero_byte_artifacts()
            status.fail_step(current_step, exc, removed_files=removed)
            raise

    def _run_named_step(self, name: str, ctx: RunContext):
        method_name = dict(self.STEP_METHODS)[name]
        return getattr(self, method_name)(ctx)

    def _is_step_artifact_valid(self, name: str, ctx: RunContext) -> bool:
        nonempty = lambda value: bool(value) and Path(value).is_file() and Path(value).stat().st_size > 0
        if name == "content":
            return bool(ctx.tts_text) and nonempty(ctx.workspace.temp_dir / "ad_script.txt")
        if name == "tts":
            return nonempty(ctx.tts_audio_path) and ctx.tts_duration > 0
        if name == "subtitle":
            return nonempty(ctx.srt_path) and bool(ctx.subtitle_filter)
        if name == "person_detection":
            return bool(ctx.person_intervals)
        if name == "clip_plan":
            return ctx.clip_plan is not None and nonempty(ctx.workspace.temp_dir / "clip_plan.json")
        if name == "timeline_render":
            return nonempty(ctx.base_merged)
        if name == "effects_prepare":
            return all(Path(path).is_file() for path in ctx.dedup_clips + ctx.use_stickers)
        if name == "composite":
            return nonempty(ctx.final_output)
        if name == "jianying_draft":
            if not config.JIANYING_DRAFT_ENABLED:
                return True
            return (
                bool(ctx.jianying_draft_dir)
                and (Path(ctx.jianying_draft_dir) / "draft_content.json").is_file()
                and nonempty(ctx.jianying_manifest_path)
            )
        if name == "record":
            return nonempty(ctx.workspace.output_dir / "随机参数记录.txt")
        return False

    def _step_content(self, ctx: RunContext):
        """Load one location, generate fact-grounded copy and persist it."""
        logger.info("===== 步骤1：读取地点并生成广告文案 =====")
        ctx.location = load_location(config.LOCATIONS_FILE, config.LOCATION_ROW)
        facts = FactLibrary.from_file(config.FACTS_FILE)
        ctx.ad_script = generate_ad_script(
            ctx.location, facts, config, supplied_text=config.SUPPLIED_SCRIPT
        )
        ctx.tts_text = ctx.ad_script.text
        script_path = ctx.workspace.temp_dir / "ad_script.txt"
        script_path.write_text(ctx.tts_text, encoding="utf-8")
        ctx.run_params["地点"] = ctx.location.full_name
        ctx.run_params["文案来源"] = ctx.ad_script.source
        ctx.run_params["广告文案"] = ctx.tts_text
        logger.info("地点：%s；文案来源：%s", ctx.location.full_name, ctx.ad_script.source)

    def _step_tts(self, ctx: RunContext):
        """Generate TTS audio and retain provider word boundaries."""
        logger.info("===== 步骤2：生成带真实时间戳的TTS语音 =====")

        ctx.tts_audio_path = str(ctx.workspace.temp_dir / "tts_audio.mp3")
        ctx.selected_voice, ctx.voice_desc = pick_random_voice()
        ctx.run_params["音色ID"] = ctx.selected_voice
        ctx.run_params["音色说明"] = ctx.voice_desc

        cache_dir = os.path.join(config.TEMP_DIR, "cache", "tts") if config.TTS_CACHE else None
        result = asyncio.run(generate_tts_result(
            ctx.tts_text, ctx.tts_audio_path, voice=ctx.selected_voice, cache_dir=cache_dir
        ))
        ctx.tts_duration = result.duration
        ctx.speech_boundaries = list(result.boundaries)
        ctx.run_params["语音时长"] = f"{ctx.tts_duration:.2f}秒"
        ctx.run_params["TTS缓存"] = "命中" if result.cache_hit else "新生成"
        logger.info(f"TTS语音生成完成，音色：{ctx.selected_voice}（{ctx.voice_desc}），时长：{ctx.tts_duration:.2f}秒")

    def _step_subtitle(self, ctx: RunContext):
        """Generate SRT from the timestamps emitted with the actual speech."""
        logger.info("\n===== 步骤3：根据真实语音时间戳生成字幕 =====")
        ctx.srt_path = str(ctx.workspace.temp_dir / "auto_subtitle.srt")
        ctx.timing_source = generate_srt_from_boundaries(
            ctx.tts_text, ctx.speech_boundaries, ctx.tts_duration, ctx.srt_path
        )
        segmenter = segment_caption_deepseek if config.DEEPSEEK_API_KEY else None
        ai_layout_calls = optimize_srt_layout(
            ctx.srt_path,
            max_chars_per_line=config.SUBTITLE_MAX_CHARS_PER_LINE,
            segmenter=segmenter,
        )
        ctx.run_params["字幕时间来源"] = ctx.timing_source
        ctx.run_params["字幕AI排版次数"] = str(ai_layout_calls)

        param_file_path = os.path.join(config.SUBTITLE_DIR, config.SUBTITLE_PARAM_FILE)
        ctx.subtitle_filter = read_subtitle_filter_param(param_file_path, ctx.srt_path)

        # 从字体库随机选字体，替换字幕中的FontName
        ctx.random_font = pick_random_font()
        ctx.run_params["字幕字体"] = ctx.random_font
        ctx.subtitle_filter = re.sub(r"FontName=[^,]+", f"FontName={ctx.random_font}", ctx.subtitle_filter)
        ctx.subtitle_filter = move_subtitle_down(
            ctx.subtitle_filter, config.SUBTITLE_DOWN_RATIO
        )
        ctx.subtitle_filter = set_subtitle_font_size(
            ctx.subtitle_filter, config.SUBTITLE_FONT_SIZE
        )
        logger.info(f"字幕滤镜参数（字体已替换为{ctx.random_font}）：{ctx.subtitle_filter}")

    def _step_person_detection(self, ctx: RunContext):
        """Find the source-time intervals in which at least one person appears."""
        raw_videos = get_target_files(config.RAW_VIDEO_DIR, ".mp4")
        if not raw_videos:
            raise FileNotFoundError(f"{config.RAW_VIDEO_DIR} 内没有找到MP4视频")
        logger.info("\n===== 步骤4：检测人物出镜区间 =====")
        for path in raw_videos:
            if config.PERSON_DETECTION_ENABLED:
                found = detect_person_intervals(
                    path, os.path.join(config.TEMP_DIR, "cache", "persons"),
                    model_name=config.PERSON_MODEL,
                    confidence=config.PERSON_CONFIDENCE,
                    sample_fps=config.PERSON_SAMPLE_FPS,
                    merge_gap=config.PERSON_INTERVAL_GAP,
                    minimum_duration=config.PERSON_MIN_INTERVAL,
                )
            else:
                duration = probe_media_cached(
                    path, os.path.join(config.TEMP_DIR, "cache", "probe")
                ).duration
                found = [PersonInterval(path, 0.0, duration)]
            ctx.person_intervals.extend(found)
        if not ctx.person_intervals:
            raise RuntimeError("所有素材都没有检测到人物，请更换素材或使用 --no-person-detection 调试")
        random.shuffle(ctx.person_intervals)
        ctx.run_params["人物区间数"] = str(len(ctx.person_intervals))
        ctx.run_params["人物源时长"] = f"{sum(x.duration for x in ctx.person_intervals):.2f}秒"

    def _step_clip_plan(self, ctx: RunContext):
        logger.info("\n===== 步骤5：根据旁白与人物区间规划倍速 =====")
        ctx.clip_plan = plan_person_timeline(
            ctx.person_intervals,
            ctx.tts_duration,
            preferred_speed=config.PREFERRED_SPEED,
            minimum_speed=config.MINIMUM_SPEED,
        )
        ctx.run_params["实际画面倍速"] = f"{ctx.clip_plan.speed:.3f}x"
        plan_path = ctx.workspace.temp_dir / "clip_plan.json"
        plan_path.write_text(json.dumps({
            "speed": ctx.clip_plan.speed,
            "narration_duration": ctx.clip_plan.narration_duration,
            "available_source_duration": ctx.clip_plan.available_source_duration,
            "items": [item.__dict__ for item in ctx.clip_plan.items],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _step_timeline_render(self, ctx: RunContext):
        logger.info("\n===== 步骤6：一次编码渲染人物时间线 =====")
        ctx.base_merged = str(ctx.workspace.temp_dir / "base_timeline.mp4")
        render_timeline(ctx.clip_plan, ctx.base_merged)
        logger.info("人物时间线完成：%s", ctx.base_merged)

    def _step5_dedup(self, ctx: RunContext):
        """步骤5.5+5.6：去重素材切片 + 随机选滤镜 + 随机选贴纸"""
        logger.info("\n===== 步骤5.5：去重素材切片 + 随机选层 =====")
        dedup_videos = get_target_files(config.DEDUP_DIR, ".mp4")
        ctx.dedup_clips = slice_dedup_videos(
            dedup_videos, ctx.tts_duration, temp_dir=str(ctx.workspace.temp_dir)
        )
        ctx.num_layers = len(ctx.dedup_clips)
        logger.info(f"共{ctx.num_layers}段去重切片，全部叠加，每层透明度{config.DEDUP_ALPHA}")

        logger.info("\n===== 步骤5.6：加载随机滤镜 =====")
        ctx.selected_filters = load_random_filters(config.NUM_RANDOM_FILTERS)
        ctx.run_params["滤镜组合"] = "、".join([f[0] for f in ctx.selected_filters])

        ctx.use_stickers = pick_random_stickers()
        ctx.run_params["贴纸组合"] = "、".join([os.path.basename(s) for s in ctx.use_stickers])

    def _step6_effects_and_composite(self, ctx: RunContext):
        """步骤6：构建完整滤镜链 + 执行最终合成（去重+滤镜+贴纸+字幕+替换TTS音频）"""
        # 构建完整的 filter_complex 滤镜链 + 输入参数
        input_cmds, full_filter_complex = build_final_filter_complex(
            base_video=ctx.base_merged,
            tts_audio=ctx.tts_audio_path,
            dedup_clips=ctx.dedup_clips,
            selected_filters=ctx.selected_filters,
            sticker_paths=ctx.use_stickers,
            subtitle_filter=ctx.subtitle_filter
        )

        ctx.final_output = str(ctx.workspace.output_dir / "final_video_with_tts.mp4")
        final_cmd = build_final_composite_command(
            input_cmds,
            full_filter_complex,
            config.get_video_encode_args(),
            ctx.final_output,
            narration_duration=ctx.tts_duration,
        )

        logger.info("\n===== 步骤6：多层去重叠加 + 四角贴纸 + 烧录字幕 + 替换TTS语音 =====")
        run_ffmpeg(final_cmd)
        final_duration = probe_media(ctx.final_output).duration
        if abs(final_duration - ctx.tts_duration) > 0.15:
            raise RuntimeError(
                f"最终视频与旁白时长不一致：视频 {final_duration:.2f} 秒，"
                f"旁白 {ctx.tts_duration:.2f} 秒"
            )
        logger.info(f"\n全部工序执行完毕！最终成品：{ctx.final_output}")
        logger.info(f"视频总时长：{ctx.tts_duration:.2f}秒（与TTS语音对齐）")
        logger.info(f"去重图层：{ctx.num_layers}层，每层透明度{config.DEDUP_ALPHA}")
        if ctx.selected_filters:
            logger.info(f"应用滤镜：{', '.join([f[0] for f in ctx.selected_filters])}")

    def _step7_write_record(self, ctx: RunContext):
        """步骤7：写入随机参数记录文件"""
        ctx.run_params["去重图层数"] = f"{ctx.num_layers}层，每层透明度{config.DEDUP_ALPHA}"
        ctx.run_params["贴纸缩放"] = f"{config.STICKER_SCALE*100:.0f}%"
        ctx.run_params["贴纸透明度"] = f"{config.STICKER_ALPHA*100:.0f}%"
        ctx.run_params["滤镜混合强度"] = f"{config.FILTER_BLEND_OPACITY*100:.0f}%"
        write_params_record(str(ctx.workspace.output_dir), ctx.run_params)

    def _step_jianying_draft(self, ctx: RunContext):
        """Create a separate editable portrait draft from the exact clip plan."""
        if not config.JIANYING_DRAFT_ENABLED:
            logger.info("剪映草稿输出已在配置中关闭")
            return
        logger.info("\n===== 步骤7：生成可编辑剪映草稿 =====")
        if ctx.clip_plan is None:
            raise RuntimeError("缺少剪辑计划，无法生成剪映草稿")
        blueprint = build_draft_blueprint(
            ctx.output_name,
            ctx.clip_plan,
            ctx.tts_audio_path,
            ctx.srt_path,
            DEFAULT_PORTRAIT_PRESET,
            dedup_paths=ctx.dedup_clips,
            dedup_alpha=config.DEDUP_ALPHA,
            sticker_paths=ctx.use_stickers,
            selected_filters=ctx.selected_filters,
            sticker_scale=config.STICKER_SCALE,
            sticker_alpha=config.STICKER_ALPHA,
            filter_intensity=config.FILTER_BLEND_OPACITY * 100,
        )
        draft_root = ctx.workspace.output_dir / "jianying_draft"
        result = generate_jianying_draft(blueprint, draft_root)
        report = validate_draft_structure(result.draft_dir)
        report_path = ctx.workspace.output_dir / "jianying_compatibility.json"
        write_compatibility_report(report, report_path)
        if not report.passed:
            raise RuntimeError("剪映草稿结构检查失败：" + "；".join(report.issues))
        ctx.jianying_draft_dir = str(result.draft_dir)
        ctx.jianying_manifest_path = str(result.manifest_path)
        ctx.compatibility_report_path = str(report_path)
        ctx.run_params["剪映草稿"] = ctx.jianying_draft_dir
        ctx.run_params["剪映兼容状态"] = report.status
