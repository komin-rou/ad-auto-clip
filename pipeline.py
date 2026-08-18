"""
主流程编排模块
VideoPipeline 类按顺序执行所有步骤，RunContext 在步骤间传递状态
"""
import os
import re
import time
import asyncio
from dataclasses import dataclass, field
from typing import List, Tuple

from config import config
from logger import logger
from utils import (
    check_ffmpeg_installed,
    run_ffmpeg,
    get_target_files,
    get_audio_duration,
    make_dir_safe,
)
from libraries import (
    pick_random_voice,
    pick_random_font,
    load_random_filters,
    pick_random_stickers,
)
from tts import generate_tts
from subtitle import generate_srt, read_subtitle_filter_param
from video_processor import preprocess_clip, join_clips, slice_dedup_videos
from effects import build_final_filter_complex
from output_manager import ensure_output_dir, write_params_record


@dataclass
class RunContext:
    """运行上下文，在各步骤间传递状态"""
    output_name: str
    run_params: dict = field(default_factory=dict)
    # TTS相关
    tts_text: str = ""
    tts_audio_path: str = ""
    tts_duration: float = 0.0
    selected_voice: str = ""
    voice_desc: str = ""
    # 字幕相关
    srt_path: str = ""
    subtitle_filter: str = ""
    random_font: str = ""
    # 视频处理相关
    per_clip_duration: float = 0.0
    speed_temp_clips: List[str] = field(default_factory=list)
    base_merged: str = ""
    # 去重相关
    dedup_clips: List[str] = field(default_factory=list)
    num_layers: int = 0
    # 特效相关
    selected_filters: List[Tuple[str, str]] = field(default_factory=list)
    use_stickers: List[str] = field(default_factory=list)
    # 输出
    final_output: str = ""


class VideoPipeline:
    """广告视频自动化混剪主流程"""

    def run(self, output_name: str) -> RunContext:
        """
        执行完整的视频生成流程
        :param output_name: 输出子目录名
        :return: RunContext 运行上下文
        """
        # 前置校验
        if not check_ffmpeg_installed():
            logger.info("错误：系统未检测到FFmpeg，请将ffmpeg配置到系统环境变量！")
            raise SystemExit(1)

        # 初始化上下文
        ctx = RunContext(output_name=output_name)
        ctx.run_params["输出目录"] = output_name
        ctx.run_params["运行时间"] = time.strftime("%Y-%m-%d %H:%M:%S")

        # 确保输出目录存在（会修改 config.OUTPUT_SUBDIR）
        ensure_output_dir(output_name)
        make_dir_safe(config.TEMP_DIR)

        # 按步骤执行
        self._step1_tts(ctx)
        self._step2_subtitle(ctx)
        self._step3_preprocess_clips(ctx)
        self._step4_join_clips(ctx)
        self._step5_dedup(ctx)
        self._step6_effects_and_composite(ctx)
        self._step7_write_record(ctx)

        return ctx

    def _step1_tts(self, ctx: RunContext):
        """步骤1：读取文本 + 随机选音色 + 生成TTS语音"""
        logger.info("===== 步骤1：生成TTS语音 =====")
        tts_text_path = os.path.join(config.SUBTITLE_DIR, config.TTS_TEXT_FILE)
        if not os.path.exists(tts_text_path):
            logger.info(f"错误：找不到TTS文本文件 {tts_text_path}")
            raise SystemExit(1)
        with open(tts_text_path, "r", encoding="utf-8") as f:
            ctx.tts_text = f.read().strip()
        logger.info(f"读取TTS文本：{tts_text_path}")
        logger.info(f"文本内容：{ctx.tts_text}")

        ctx.tts_audio_path = os.path.join(config.TEMP_DIR, "tts_audio.mp3")
        ctx.selected_voice, ctx.voice_desc = pick_random_voice()
        ctx.run_params["音色ID"] = ctx.selected_voice
        ctx.run_params["音色说明"] = ctx.voice_desc

        asyncio.run(generate_tts(ctx.tts_text, ctx.tts_audio_path, voice=ctx.selected_voice))
        ctx.tts_duration = get_audio_duration(ctx.tts_audio_path)
        ctx.run_params["语音时长"] = f"{ctx.tts_duration:.2f}秒"
        logger.info(f"TTS语音生成完成，音色：{ctx.selected_voice}（{ctx.voice_desc}），时长：{ctx.tts_duration:.2f}秒")

    def _step2_subtitle(self, ctx: RunContext):
        """步骤2：准备字幕文件 + 随机选字体 + 生成字幕滤镜参数"""
        logger.info("\n===== 步骤2：准备字幕文件 =====")
        user_srt_path = os.path.join(config.SUBTITLE_DIR, config.SUBTITLE_SRT_FILE)
        if os.path.exists(user_srt_path):
            ctx.srt_path = user_srt_path
            logger.info(f"使用用户提供的字幕文件：{ctx.srt_path}")
        else:
            ctx.srt_path = os.path.join(config.TEMP_DIR, "auto_subtitle.srt")
            logger.info(f"未找到 {config.SUBTITLE_SRT_FILE}，自动生成字幕...")
            generate_srt(ctx.tts_text, ctx.tts_duration, ctx.srt_path)

        param_file_path = os.path.join(config.SUBTITLE_DIR, config.SUBTITLE_PARAM_FILE)
        ctx.subtitle_filter = read_subtitle_filter_param(param_file_path, ctx.srt_path)

        # 从字体库随机选字体，替换字幕中的FontName
        ctx.random_font = pick_random_font()
        ctx.run_params["字幕字体"] = ctx.random_font
        ctx.subtitle_filter = re.sub(r"FontName=[^,]+", f"FontName={ctx.random_font}", ctx.subtitle_filter)
        logger.info(f"字幕滤镜参数（字体已替换为{ctx.random_font}）：{ctx.subtitle_filter}")

    def _step3_preprocess_clips(self, ctx: RunContext):
        """步骤3+4：计算每段裁剪时长 + 所有视频二倍速+统一化+裁剪+静音"""
        raw_videos = get_target_files(config.RAW_VIDEO_DIR, ".mp4")
        if len(raw_videos) < 1:
            logger.info(f"错误：{config.RAW_VIDEO_DIR} 内没有找到MP4视频")
            raise SystemExit(1)

        num_clips = len(raw_videos)
        ctx.per_clip_duration = ctx.tts_duration / num_clips
        logger.info(f"\n===== 步骤3：共{num_clips}段素材，每段裁剪到 {ctx.per_clip_duration:.2f} 秒 =====")

        use_videos = raw_videos

        logger.info(f"\n===== 步骤4：对{num_clips}段视频进行二倍速+统一化+裁剪+静音处理 =====")
        for idx, vid_path in enumerate(use_videos):
            out_speed = os.path.join(config.TEMP_DIR, f"speed_clip_{idx}.mp4")
            preprocess_clip(vid_path, out_speed, ctx.per_clip_duration)
            ctx.speed_temp_clips.append(out_speed)
            logger.info(f"第{idx+1}/{num_clips}段处理完成，裁剪到 {ctx.per_clip_duration:.2f} 秒（已静音）")

    def _step4_join_clips(self, ctx: RunContext):
        """步骤5：拼接所有视频"""
        num_clips = len(ctx.speed_temp_clips)
        logger.info(f"\n===== 步骤5：拼接{num_clips}段视频 =====")
        ctx.base_merged = os.path.join(config.TEMP_DIR, "base_merged_video.mp4")
        join_clips(ctx.speed_temp_clips, ctx.base_merged)
        logger.info(f"基础拼接完成：{ctx.base_merged}")

    def _step5_dedup(self, ctx: RunContext):
        """步骤5.5+5.6：去重素材切片 + 随机选滤镜 + 随机选贴纸"""
        logger.info("\n===== 步骤5.5：去重素材切片 + 随机选层 =====")
        dedup_videos = get_target_files(config.DEDUP_DIR, ".mp4")
        ctx.dedup_clips = slice_dedup_videos(dedup_videos, ctx.tts_duration)
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

        ctx.final_output = os.path.join(config.OUTPUT_DIR, "final_video_with_tts.mp4")
        final_cmd = input_cmds + [
            "-filter_complex", full_filter_complex,
            "-map", "[out_video]",
            "-map", "1:a",
            *config.get_video_encode_args(),
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            ctx.final_output
        ]

        logger.info("\n===== 步骤6：多层去重叠加 + 四角贴纸 + 烧录字幕 + 替换TTS语音 =====")
        run_ffmpeg(final_cmd)
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
        write_params_record(config.OUTPUT_DIR, ctx.run_params)
