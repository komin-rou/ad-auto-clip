"""
通用工具函数模块
纯工具，不依赖业务逻辑，不依赖config
"""
import os
import subprocess

from logger import logger


def make_dir_safe(path: str):
    """安全创建目录，已存在则不报错"""
    os.makedirs(path, exist_ok=True)


def check_ffmpeg_installed() -> bool:
    """检测系统环境变量中是否存在ffmpeg"""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )
        return True
    except Exception:
        return False


def run_ffmpeg(cmd_list: list):
    """
    执行ffmpeg命令，统一日志+异常捕获
    注意：必须使用 shell=False，否则 force_style 中的 &H 颜色值会被 cmd 解析为命令连接符
    """
    cmd_str = " ".join(cmd_list)
    logger.info(f"\n>>>>>>>>>> 执行FFmpeg命令:\n{cmd_str}\n")
    try:
        proc = subprocess.run(
            cmd_list,
            shell=False,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if proc.returncode != 0:
            logger.info(f"FFmpeg执行失败！错误日志:\n{proc.stderr}")
            raise RuntimeError("FFmpeg命令执行异常")
        return proc
    except Exception as e:
        logger.info(f"运行FFmpeg出错: {str(e)}")
        raise SystemExit(1)


def get_target_files(folder: str, suffix: str) -> list:
    """获取指定文件夹下指定后缀文件绝对路径列表（按文件名排序）"""
    if not os.path.isdir(folder):
        return []
    res = []
    suffix_low = suffix.lower()
    for fname in os.listdir(folder):
        if fname.lower().endswith(suffix_low):
            full_path = os.path.abspath(os.path.join(folder, fname))
            res.append(full_path)
    return sorted(res)


def get_audio_duration(audio_path: str) -> float:
    """获取音频文件时长（秒）"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return float(proc.stdout.strip())


def get_video_duration(video_path: str) -> float:
    """获取视频文件时长（秒）"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return float(proc.stdout.strip())
