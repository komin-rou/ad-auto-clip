"""
视频处理模块
封装视频预处理、拼接、去重切片等核心FFmpeg操作
"""
import os

from clip_planner import ClipPlan

from config import config
from logger import logger
from cache_manager import get_cache_manager
from utils import run_ffmpeg, get_video_duration, probe_media_cached


def build_aspect_filter(width: int, height: int, fps: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps}"
    )


def build_timeline_command(
    plan: ClipPlan,
    output_path: str,
    width: int,
    height: int,
    fps: int,
    encode_args: list[str],
) -> list[str]:
    if not plan.items:
        raise ValueError("剪辑计划为空")
    command = ["ffmpeg", "-y"]
    for item in plan.items:
        command.extend(["-i", item.source])
    filters = []
    labels = []
    for index, item in enumerate(plan.items):
        label = f"v{index}"
        labels.append(f"[{label}]")
        filters.append(
            f"[{index}:v]trim=start={item.source_start:.6f}:end={item.source_end:.6f},"
            f"setpts=(PTS-STARTPTS)/{item.speed:.6g},"
            f"{build_aspect_filter(width, height, fps)}[{label}]"
        )
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[outv]")
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[outv]", "-an", *encode_args,
        "-pix_fmt", "yuv420p", "-t", f"{plan.narration_duration:.6f}", output_path,
    ])
    return command


def render_timeline(plan: ClipPlan, output_path: str) -> str:
    resolution = config.TARGET_RESOLUTION.lower().replace("x", ":").split(":")
    width, height = int(resolution[0]), int(resolution[1])
    run_ffmpeg(build_timeline_command(
        plan, output_path, width, height, config.TARGET_FPS, config.get_video_encode_args()
    ))
    return output_path


def preprocess_clip(input_path: str, output_path: str, duration: float) -> str:
    """
    单段视频预处理：二倍速 + 统一化（分辨率/色彩/锐度/帧率）+ 裁剪 + 静音
    :param input_path: 原始视频路径
    :param output_path: 输出视频路径
    :param duration: 裁剪到多少秒
    :return: output_path
    """
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        # 画面：二倍速 + 拉升1080x1920 + 调色 + 锐化 + 统一30fps
        "-vf", (
            f"setpts=PTS/{config.SPEED_RATE},"
            f"{build_aspect_filter(1080, 1920, config.TARGET_FPS)},"
            "eq=contrast=1.1:saturation=1.15,unsharp=5:5:0.8"
        ),
        # 音频：二倍速 + 静音（原视频音频不要，后面用TTS替换）
        "-af", f"atempo={config.SPEED_RATE},volume=0",
        # 裁剪时长
        "-t", str(duration),
        # 重新编码（不能用-c copy，因为滤镜处理后必须重编码）
        *config.get_video_encode_args(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        output_path
    ]
    run_ffmpeg(ffmpeg_cmd)
    return output_path


def join_clips(clip_paths: list, output_path: str, temp_dir: str = None) -> str:
    """
    多段视频顺序拼接
    注意：必须重新编码，不能用 -c copy，否则四段视频编码参数不一致会导致黑屏
    末尾加 -async 1 缓解 Non-monotonic DTS 警告
    :param clip_paths: 要拼接的视频路径列表
    :param output_path: 拼接后输出路径
    :return: output_path
    """
    # 生成 concat 所需的文件列表
    concat_list_txt = os.path.join(temp_dir or os.path.dirname(output_path), "concat_list.txt")
    with open(concat_list_txt, "w", encoding="utf-8") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_txt,
        # 重新编码（关键：不能用 -c copy）
        *config.get_video_encode_args(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        # 缓解音频时间戳错乱
        "-async", "1",
        output_path
    ]
    run_ffmpeg(concat_cmd)
    return output_path


def slice_dedup_videos(dedup_videos: list, segment_duration: float, temp_dir: str = None) -> list:
    """
    把所有去重视频按 segment_duration 切片，返回所有切片路径列表
    例如：90秒视频 / 17.66秒 = 5段
    注意：切片必须加 -an 去音频，否则叠加时多个音频流冲突
    支持缓存：相同源文件+相同时间段的切片第二次运行直接复用
    :param dedup_videos: 去重视频路径列表
    :param segment_duration: 每段切片时长（秒）
    :return: 切片路径列表
    """
    temp_dir = temp_dir or config.TEMP_DIR
    cache_manager = get_cache_manager(os.path.join(config.TEMP_DIR, "cache"))
    all_clips = []
    clip_idx = 0
    cache_hit = 0
    cache_miss = 0

    for vid_path in dedup_videos:
        vid_duration = probe_media_cached(
            vid_path, os.path.join(config.TEMP_DIR, "cache", "probe")
        ).duration
        num_segments = int(vid_duration // segment_duration)
        logger.info(f"去重视频 {os.path.basename(vid_path)} 时长{vid_duration:.1f}秒，可切{num_segments}段")

        for seg_idx in range(num_segments):
            start_time = seg_idx * segment_duration
            out_path = os.path.join(temp_dir, f"dedup_seg_{clip_idx}.mp4")

            # 先查缓存
            cached_path = cache_manager.get(vid_path, start_time, segment_duration)
            if cached_path:
                # 缓存命中，直接复制
                import shutil
                shutil.copy2(cached_path, out_path)
                cache_hit += 1
                logger.info(f"  [缓存命中] 第{seg_idx+1}段，直接复用")
            else:
                # 缓存未命中，用FFmpeg切片
                cache_miss += 1
                ffmpeg_cmd = [
                    "ffmpeg", "-y", "-ss", str(start_time), "-i", vid_path,
                    "-vf", build_aspect_filter(1080, 1920, config.TARGET_FPS),
                    "-t", str(segment_duration),
                    # 去音频（关键：去重图层不需要音频）
                    "-an",
                    *config.get_video_encode_args(), "-pix_fmt", "yuv420p",
                    out_path
                ]
                run_ffmpeg(ffmpeg_cmd)
                # 存入缓存
                cache_manager.put(vid_path, start_time, segment_duration, out_path)

            all_clips.append(out_path)
            clip_idx += 1

    logger.info(f"去重素材切片完成，共{len(all_clips)}段可用（缓存命中{cache_hit}段，新切片{cache_miss}段）")
    return all_clips
