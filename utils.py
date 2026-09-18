"""Shared filesystem and subprocess utilities with actionable diagnostics."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

from logger import logger


Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class ToolCheck:
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool


class CommandExecutionError(RuntimeError):
    pass


class MediaProbeError(RuntimeError):
    pass


def make_dir_safe(path: str):
    os.makedirs(path, exist_ok=True)


def _invoke(
    args: list[str],
    runner: Runner,
    timeout: int | None,
) -> subprocess.CompletedProcess:
    try:
        return runner(
            args,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CommandExecutionError(f"找不到外部工具：{args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandExecutionError(f"外部命令超时：{args[0]}（{timeout}秒）") from exc
    except OSError as exc:
        raise CommandExecutionError(f"无法启动外部工具 {args[0]}：{exc}") from exc


def _stderr_tail(stderr: str | bytes | None, limit: int = 2000) -> str:
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", errors="replace")
    else:
        text = stderr or ""
    return text.strip()[-limit:]


def run_command(
    args: list[str],
    context: str,
    runner: Runner = subprocess.run,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    result = _invoke(args, runner, timeout)
    if result.returncode != 0:
        detail = _stderr_tail(result.stderr) or "没有错误输出"
        raise CommandExecutionError(
            f"{context}失败（退出码 {result.returncode}）：{detail}"
        )
    return result


def check_tool(name: str, runner: Runner = subprocess.run) -> ToolCheck:
    try:
        result = _invoke([name, "-version"], runner, timeout=10)
    except CommandExecutionError as exc:
        return ToolCheck(name, False, str(exc))
    if result.returncode != 0:
        return ToolCheck(name, False, _stderr_tail(result.stderr) or f"退出码 {result.returncode}")
    first_line = ((result.stdout or result.stderr or "").splitlines() or ["可用"])[0]
    return ToolCheck(name, True, first_line)


def check_ffmpeg_installed() -> bool:
    return check_tool("ffmpeg").available and check_tool("ffprobe").available


def run_ffmpeg(cmd_list: list[str]):
    logger.info("\n>>>>>>>>>> 执行FFmpeg命令:\n%s\n", " ".join(cmd_list))
    try:
        return run_command(cmd_list, context="FFmpeg处理")
    except CommandExecutionError as exc:
        logger.error(str(exc))
        raise


def probe_media(
    media_path: str,
    runner: Runner = subprocess.run,
    require_video: bool = True,
) -> MediaInfo:
    path = Path(media_path)
    if not path.is_file():
        raise MediaProbeError(f"媒体文件不存在：{path}")
    args = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of", "json", str(path),
    ]
    try:
        result = run_command(args, context=f"读取媒体信息 {path.name}", runner=runner, timeout=30)
        payload = json.loads(result.stdout or "{}")
    except (CommandExecutionError, json.JSONDecodeError, TypeError) as exc:
        raise MediaProbeError(f"无法读取媒体信息 {path}：{exc}") from exc

    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if require_video and video is None:
        raise MediaProbeError(f"媒体没有视频流：{path}")
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise MediaProbeError(f"媒体时长无效：{path}") from exc
    if duration <= 0:
        raise MediaProbeError(f"媒体时长必须大于零：{path}")

    fps = None
    if video and video.get("r_frame_rate") not in (None, "0/0"):
        try:
            fps = float(Fraction(video["r_frame_rate"]))
        except (ValueError, ZeroDivisionError):
            fps = None
    return MediaInfo(
        path=str(path),
        duration=duration,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=fps,
        has_audio=any(item.get("codec_type") == "audio" for item in streams),
    )


def probe_media_cached(
    media_path: str,
    cache_dir: str,
    runner: Runner = subprocess.run,
    require_video: bool = True,
) -> MediaInfo:
    """Persist FFprobe results using the media file fingerprint as the key."""
    path = Path(media_path)
    if not path.is_file():
        raise MediaProbeError(f"媒体文件不存在：{path}")
    stat = path.stat()
    raw_key = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{require_video}"
    key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / f"{key}.json"
    if cache_path.is_file():
        try:
            return MediaInfo(**json.loads(cache_path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            cache_path.unlink(missing_ok=True)
    info = probe_media(str(path), runner=runner, require_video=require_video)
    cache_path.write_text(json.dumps(info.__dict__, ensure_ascii=False), encoding="utf-8")
    return info


def validate_runtime(app_config) -> None:
    problems = []
    for name in ("ffmpeg", "ffprobe"):
        result = check_tool(name)
        if not result.available:
            problems.append(f"{name}: {result.detail}")
    if problems:
        raise RuntimeError("运行环境预检失败：\n" + "\n".join(problems))

    if app_config.VIDEO_ENCODER == "h264_nvenc":
        args = [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=128x128:d=0.1", "-frames:v", "1",
            "-c:v", "h264_nvenc", "-preset", app_config.NVENC_PRESET,
            "-f", "null", "-",
        ]
        try:
            run_command(args, context="NVIDIA NVENC 编码器预检", timeout=15)
        except CommandExecutionError as exc:
            logger.warning("%s；本次任务自动改用 libx264", exc)
            app_config.VIDEO_ENCODER = "libx264"


def get_target_files(folder: str, suffix: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    suffix_low = suffix.lower()
    return sorted(
        os.path.abspath(os.path.join(folder, name))
        for name in os.listdir(folder)
        if name.lower().endswith(suffix_low)
    )


def get_audio_duration(audio_path: str) -> float:
    return probe_media(audio_path, require_video=False).duration


def get_video_duration(video_path: str) -> float:
    return probe_media(video_path, require_video=True).duration
