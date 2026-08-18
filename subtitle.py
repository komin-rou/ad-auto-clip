"""
字幕处理模块
封装字幕文件准备、SRT生成、字幕滤镜参数生成
"""
import os
import re

from logger import logger


def format_srt_time(seconds: float) -> str:
    """把秒数转成SRT字幕时间格式 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(text: str, total_duration: float, output_path: str):
    """
    把文本按标点分句，自动生成SRT字幕文件（备用方案）
    当用户没有提供 caption.srt 时使用
    """
    sentences = re.split(r'(?<=[。！？])', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) == 0:
        sentences = [text]
    per_sentence_duration = total_duration / len(sentences)
    with open(output_path, "w", encoding="utf-8") as f:
        for idx, sentence in enumerate(sentences):
            start_time = idx * per_sentence_duration
            end_time = (idx + 1) * per_sentence_duration
            f.write(f"{idx + 1}\n")
            f.write(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}\n")
            f.write(f"{sentence}\n\n")
    logger.info(f"自动生成SRT完成，共{len(sentences)}句，每句约{per_sentence_duration:.2f}秒")


def read_subtitle_filter_param(param_file_path: str, srt_path: str) -> str:
    """
    读取字幕滤镜参数文件，返回完整的subtitles滤镜字符串
    处理路径转义：反斜杠转正斜杠，冒号加反斜杠转义，路径用单引号包裹
    """
    # 路径转义：D:\ad_auto\subtitles\caption.srt -> 'D\:/ad_auto/subtitles/caption.srt'
    srt_path_filter = srt_path.replace("\\", "/").replace(":", "\\:")

    if os.path.exists(param_file_path):
        with open(param_file_path, "r", encoding="utf-8") as f:
            param_content = f.read().strip()
        # 把参数文件里的占位路径替换成实际转义后的路径
        param_content = param_content.replace(
            "subtitles=caption.srt:",
            f"subtitles='{srt_path_filter}':"
        )
        return param_content
    else:
        # 参数文件不存在时用默认样式
        return f"subtitles='{srt_path_filter}':force_style='FontSize=28,MarginV=140'"
