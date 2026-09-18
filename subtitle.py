"""
字幕处理模块
封装字幕文件准备、SRT生成、字幕滤镜参数生成
"""
import os
import re
from pathlib import Path

from logger import logger


def move_subtitle_down(filter_text: str, ratio: float = 0.15) -> str:
    """Move bottom-aligned subtitles down by reducing their bottom margin."""
    if not 0 <= ratio < 1:
        raise ValueError("字幕下移比例必须在 0 到 1 之间")

    def replace(match):
        current = int(match.group(1))
        return f"MarginV={max(0, round(current * (1 - ratio)))}"

    adjusted, count = re.subn(r"MarginV=(\d+)", replace, filter_text, count=1)
    if count == 0:
        logger.warning("字幕样式没有 MarginV，无法应用下移比例")
    return adjusted


def set_subtitle_font_size(filter_text: str, font_size: int) -> str:
    """Override the ASS subtitle font size in an FFmpeg subtitles filter."""
    if font_size < 1:
        raise ValueError("字幕字号必须大于 0")
    adjusted, count = re.subn(r"FontSize=\d+", f"FontSize={font_size}", filter_text, count=1)
    if count == 0:
        logger.warning("字幕样式没有 FontSize，无法覆盖字号")
    return adjusted


def _parse_srt_time(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _local_caption_segments(text: str, max_chars: int) -> list[str]:
    compact = re.sub(r"\s+", "", text)
    if len(compact) <= max_chars:
        return [compact]
    parts = [part for part in re.split(r"(?<=[，。！？；、,.!?;])", compact) if part]
    segments, current = [], ""
    for part in parts:
        while len(part) > max_chars:
            if current:
                segments.append(current)
                current = ""
            segments.append(part[:max_chars])
            part = part[max_chars:]
        if current and len(current) + len(part) > max_chars:
            segments.append(current)
            current = part
        else:
            current += part
    if current:
        segments.append(current)
    return segments


def _two_line_text(text: str, max_chars_per_line: int) -> str:
    compact = re.sub(r"\s+", "", text)
    if len(compact) <= max_chars_per_line:
        return compact
    split_at = min(max_chars_per_line, len(compact))
    for index in range(split_at, max(0, split_at - 5), -1):
        if compact[index - 1] in "，。！？；、,.!?;":
            split_at = index
            break
    return compact[:split_at] + "\n" + compact[split_at:]


def optimize_srt_layout(
    srt_path: str | Path,
    max_chars_per_line: int = 12,
    segmenter=None,
) -> int:
    """Guarantee at most two lines per cue, asking AI only for overflow cues."""
    if max_chars_per_line < 1:
        raise ValueError("每行字幕字数必须大于 0")
    path = Path(srt_path)
    blocks = [block for block in re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8").strip()) if block]
    output_cues = []
    ai_calls = 0
    caption_limit = max_chars_per_line * 2
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            raise ValueError(f"SRT 条目格式无效：{block[:80]}")
        start_text, end_text = (item.strip() for item in lines[1].split("-->", 1))
        start, end = _parse_srt_time(start_text), _parse_srt_time(end_text)
        original_lines = lines[2:]
        text = re.sub(r"\s+", "", "".join(original_lines))
        overflow = len(original_lines) > 2 or _visible_length(text) > caption_limit
        segments = None
        if overflow and segmenter is not None:
            ai_calls += 1
            try:
                proposed = [re.sub(r"\s+", "", item) for item in segmenter(text, caption_limit)]
                if (
                    proposed
                    and "".join(proposed) == text
                    and all(0 < _visible_length(item) <= caption_limit for item in proposed)
                ):
                    segments = proposed
            except Exception as exc:
                logger.warning("大模型字幕排版失败，使用本地拆分：%s", exc)
        if segments is None:
            segments = _local_caption_segments(text, caption_limit)
        weights = [max(1, _visible_length(item)) for item in segments]
        total_weight = sum(weights)
        cursor = start
        for index, (segment, weight) in enumerate(zip(segments, weights)):
            segment_end = end if index == len(segments) - 1 else cursor + (end - start) * weight / total_weight
            output_cues.append((cursor, segment_end, _two_line_text(segment, max_chars_per_line)))
            cursor = segment_end
    with path.open("w", encoding="utf-8") as handle:
        for index, (start, end, text) in enumerate(output_cues, start=1):
            handle.write(f"{index}\n{format_srt_time(start)} --> {format_srt_time(end)}\n{text}\n\n")
    logger.info("字幕排版完成：%s条，每帧最多两行，大模型调用%s次", len(output_cues), ai_calls)
    return ai_calls


def format_srt_time(seconds: float) -> str:
    """把秒数转成SRT字幕时间格式 HH:MM:SS,mmm"""
    total_millis = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
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


def generate_srt_from_boundaries(text, boundaries, total_duration: float, output_path) -> str:
    """Generate SRT using timestamps emitted by the speech provider."""
    usable = [item for item in boundaries if item.text.strip() and item.end > item.start]
    if not usable:
        generate_srt(text, total_duration, str(output_path))
        return "estimated"
    grouped = []
    current = []
    current_chars = 0
    for item in usable:
        current.append(item)
        current_chars += len(re.sub(r"[\s，。！？、；：,.!?;:]", "", item.text))
        punctuation_end = bool(re.search(r"[，。！？；,.!?;]$", item.text.strip()))
        if current_chars >= 15 or punctuation_end:
            grouped.append(current)
            current, current_chars = [], 0
    if current:
        grouped.append(current)
    with open(output_path, "w", encoding="utf-8") as handle:
        for index, group in enumerate(grouped, start=1):
            item_start, item_end = group[0], group[-1]
            start = max(0.0, min(float(item_start.start), total_duration))
            end = max(start, min(float(item_end.end), total_duration))
            handle.write(f"{index}\n")
            handle.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
            handle.write(f"{''.join(item.text for item in group).strip()}\n\n")
    logger.info("使用 TTS 真实时间边界生成 SRT，共%s条", len(grouped))
    return "word_boundary"


def read_subtitle_filter_param(param_file_path: str, srt_path: str) -> str:
    """
    读取字幕滤镜参数文件，返回完整的subtitles滤镜字符串
    处理路径转义：反斜杠转正斜杠，冒号加反斜杠转义，路径用单引号包裹
    """
    # 路径转义：C:\project\subtitles\caption.srt -> 'C\:/project/subtitles/caption.srt'
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
