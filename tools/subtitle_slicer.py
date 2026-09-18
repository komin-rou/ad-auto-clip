"""
字幕切片工具
功能：把一段完整的文本切成带时间轴的SRT字幕文件
用法：修改下面的配置区，然后运行 python subtitle_slicer.py
"""

import os
import re
from pathlib import Path

# ====================== 【配置区】 ======================
BASE_DIR = str(Path(__file__).resolve().parents[1])
SUBTITLE_DIR = os.path.join(BASE_DIR, "subtitles")

# 输入：完整文本文件
INPUT_TEXT_FILE = "sub1.txt"

# 输出：切片后的字幕文件（SRT格式，后缀用.txt方便编辑）
OUTPUT_CAPTION_FILE = "caption_output.txt"

# 输出：字幕滤镜参数文件
OUTPUT_PARAM_FILE = "filter_parameter_output.txt"

# 字幕总时长（秒），如果填0则自动按字数估算（每秒约4个字）
TOTAL_DURATION = 0

# 每句最大字数（超过就换行，一行最多这么多字）
MAX_CHARS_PER_LINE = 12

# 每条字幕之间的间隔（秒）
GAP_BETWEEN_SUBS = 0.2

# 字幕样式参数（照着改就行）
SUBTITLE_STYLE = {
    "FontName": "SimHei",           # 字体：黑体
    "FontSize": "28",               # 字号
    "PrimaryColour": "&H00FFFFFF",  # 字体颜色：白色
    "OutlineColour": "&H00000000",  # 描边颜色：黑色
    "Outline": "2",                 # 描边宽度
    "Alignment": "2",               # 对齐方式：2=底部居中
    "MarginV": "140",               # 距离底部的像素
}
# ========================================================

def format_srt_time(seconds: float) -> str:
    """秒数转SRT时间格式 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def split_text_to_lines(text: str, max_chars: int) -> list:
    """把文本按标点分句，再按最大字数换行"""
    # 先按句号、问号、感叹号、逗号分句
    sentences = re.split(r'(?<=[。！？，、])', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    result = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            result.append(sentence)
        else:
            # 长句按最大字数硬切
            for i in range(0, len(sentence), max_chars):
                result.append(sentence[i:i + max_chars])
    return result

def estimate_duration(text: str) -> float:
    """按字数估算总时长（每秒约4个字）"""
    char_count = len(re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text))
    return max(char_count / 4.0, 3.0)

def generate_srt(lines: list, total_duration: float, gap: float) -> str:
    """生成SRT格式的字幕内容"""
    # 计算每条字幕的时长（总时长 - 间隔总和）/ 条数
    total_gap = gap * (len(lines) - 1)
    per_sub_duration = (total_duration - total_gap) / len(lines)

    srt_content = []
    current_time = 0.0

    for idx, line in enumerate(lines):
        start_time = current_time
        end_time = current_time + per_sub_duration

        srt_content.append(str(idx + 1))
        srt_content.append(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}")
        srt_content.append(line)
        srt_content.append("")  # 空行分隔

        current_time = end_time + gap

    return "\n".join(srt_content)

def generate_filter_param(style: dict) -> str:
    """生成字幕滤镜参数字符串"""
    style_parts = [f"{k}={v}" for k, v in style.items()]
    style_str = ",".join(style_parts)
    return f"subtitles=caption.srt:force_style='{style_str}'"

if __name__ == "__main__":
    # 读取输入文本
    input_path = os.path.join(SUBTITLE_DIR, INPUT_TEXT_FILE)
    if not os.path.exists(input_path):
        print(f"错误：找不到输入文件 {input_path}")
        exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read().strip()

    print(f"读取文本：{input_path}")
    print(f"原文内容：{text}")
    print(f"原文长度：{len(text)} 字符")

    # 分句换行
    lines = split_text_to_lines(text, MAX_CHARS_PER_LINE)
    print(f"\n切分成 {len(lines)} 条字幕：")
    for i, line in enumerate(lines):
        print(f"  {i+1}. {line}")

    # 确定总时长
    if TOTAL_DURATION > 0:
        total_dur = TOTAL_DURATION
    else:
        total_dur = estimate_duration(text)
        print(f"\n自动估算总时长：{total_dur:.2f} 秒")

    # 生成SRT
    srt_content = generate_srt(lines, total_dur, GAP_BETWEEN_SUBS)
    output_caption_path = os.path.join(SUBTITLE_DIR, OUTPUT_CAPTION_FILE)
    with open(output_caption_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"\n字幕文件已生成：{output_caption_path}")

    # 生成滤镜参数
    filter_param = generate_filter_param(SUBTITLE_STYLE)
    output_param_path = os.path.join(SUBTITLE_DIR, OUTPUT_PARAM_FILE)
    with open(output_param_path, "w", encoding="utf-8") as f:
        f.write(filter_param)
    print(f"滤镜参数文件已生成：{output_param_path}")
    print(f"参数内容：{filter_param}")

    print("\n===== 完成 =====")
    print(f"下一步：把 {OUTPUT_CAPTION_FILE} 改名为 caption.srt")
    print(f"      把 {OUTPUT_PARAM_FILE} 改名为 filter_parameter.txt")
    print("      然后运行 main.py 即可")
