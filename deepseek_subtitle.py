"""
DeepSeek 大模型字幕切割模块
用大模型把长文本智能切割成 SRT 字幕文件，每条严格控制 10-12 字，支持两行显示

用法：
    from deepseek_subtitle import generate_srt_deepseek
    generate_srt_deepseek(text, total_duration, output_path)
"""
import os
import re
import time
import json
import shutil

from config import config
from logger import logger
from subtitle import format_srt_time, generate_srt as generate_srt_regex


# ==================== Prompt 构造 ====================

SYSTEM_PROMPT = """你是一个专业的短视频字幕切分专家。你的任务是把一段广告口播文本，按照语义、标点和自然呼吸感，切分成多条字幕，并输出标准 SRT 格式。

【核心规则 - 必须严格遵守】
1. 每条字幕的文字总数严格控制在 10-12 个汉字之间（标点不计入字数），少于10字或多于12字都不合格
2. 如果一条语义完整的话超过12字，允许分成两行显示（SRT中用换行），但每行不超过12字，两行总字数不超过24字
3. 绝对不允许把一个完整的词或语义拆到两条字幕之间
4. 在逗号、句号、顿号、感叹号、问号、分号等标点处优先切分
5. 时间轴从 00:00:00,000 开始，到 {end_time} 结束，根据每条字数比例分配时长，字多的条时间稍长
6. 相邻字幕之间留 0.15 秒间隔，时间轴绝对不能重叠
7. 只输出纯 SRT 格式内容，不要任何解释、说明、前言、后记、markdown 代码块标记
8. 序号从 1 开始连续编号，时间格式严格为 HH:MM:SS,mmm

【两行字幕示例 - 一条字幕内换行】
1
00:00:00,000 --> 00:00:03,200
今天带大家看看施工现场
师傅正在认真测量尺寸

2
00:00:03,350 --> 00:00:06,000
方案确认之后安排制作
后续进度都会及时沟通

【单行字幕示例】
3
00:00:06,150 --> 00:00:08,500
现场细节都为你拍清楚

4
00:00:08,650 --> 00:00:11,000
确认无误之后安排安装
"""


def _build_user_prompt(text: str, total_duration: float) -> str:
    """构造用户消息"""
    return f"""请把下面这段广告口播文本切分成 SRT 字幕。

总时长：{total_duration:.2f} 秒
每条字幕 10-12 字，超长可分两行（每行≤12字）

文本：
{text}

直接输出 SRT 内容，不要多余文字。"""


# ==================== API 调用 ====================

def _call_deepseek_api(system_prompt: str, user_prompt: str) -> str:
    """
    调用 DeepSeek Chat Completions API（OpenAI 兼容格式）
    返回模型回复的纯文本
    """
    import requests

    url = f"{config.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 2048,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def segment_caption_deepseek(text: str, max_chars: int) -> list[str]:
    """Semantically split one overflowing caption without changing its text."""
    system_prompt = (
        "你是短视频字幕断句工具。把输入文字切成JSON字符串数组。"
        "不得增删、改写或调换任何字符；拼接数组必须与原文完全一致。"
        f"每个数组元素最多{max_chars}个字符。只输出JSON数组。"
    )
    raw = _call_deepseek_api(system_prompt, text)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    payload = json.loads(cleaned)
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError("大模型字幕分段结果不是字符串数组")
    return payload


def _extract_srt_content(raw_text: str) -> str:
    """
    从模型回复中提取纯 SRT 内容
    处理可能的 markdown 代码块包裹、多余说明文字等
    """
    text = raw_text.strip()

    # 去掉 markdown 代码块标记 ```srt 或 ```
    text = re.sub(r'^```(?:srt)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)

    # 找到第一个数字序号（SRT起始标志），去掉前面的说明文字
    match = re.search(r'^\s*1\s*$', text, re.MULTILINE)
    if match:
        text = text[match.start():]

    return text.strip()


def _validate_srt(srt_content: str) -> bool:
    """简单校验 SRT 格式是否合法"""
    if not srt_content:
        return False
    # 至少要有一条字幕：序号 + 时间轴 + 文本
    pattern = r'^\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*\n.+'
    return bool(re.search(pattern, srt_content, re.MULTILINE))


def _save_to_subtitles_dir(srt_content: str, source_text: str):
    """把生成的SRT额外保存一份到subtitles目录，方便用户查看和复用"""
    try:
        save_path = os.path.join(config.SUBTITLE_DIR, "deepseek_generated.srt")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        logger.info(f"[DeepSeek] 字幕已备份到 {save_path}")
    except Exception as e:
        logger.warning(f"[DeepSeek] 备份字幕到subtitles目录失败: {e}")


# ==================== 主函数 ====================

def generate_srt_deepseek(text: str, total_duration: float, output_path: str) -> bool:
    """
    用 DeepSeek 大模型把长文本切割成 SRT 字幕文件

    :param text: 完整口播文本
    :param total_duration: 语音总时长（秒），用于分配时间轴
    :param output_path: 输出 SRT 文件路径（temp目录）
    :return: True=大模型生成成功，False=降级为正则分句
    """
    # 没有 API Key，直接降级
    if not config.DEEPSEEK_API_KEY:
        logger.info("未配置 DeepSeek API Key，降级为正则分句")
        generate_srt_regex(text, total_duration, output_path)
        return False

    import requests

    end_time = format_srt_time(total_duration)
    system_prompt = SYSTEM_PROMPT.format(end_time=end_time)
    user_prompt = _build_user_prompt(text, total_duration)

    last_error = None
    for attempt in range(1, config.DEEPSEEK_MAX_RETRIES + 1):
        try:
            logger.info(f"[DeepSeek] 第 {attempt}/{config.DEEPSEEK_MAX_RETRIES} 次调用大模型切割字幕...")
            raw_response = _call_deepseek_api(system_prompt, user_prompt)
            srt_content = _extract_srt_content(raw_response)

            if _validate_srt(srt_content):
                # 保存到temp目录（程序运行用）
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                # 额外备份到subtitles目录（用户查看用）
                _save_to_subtitles_dir(srt_content, text)
                # 统计条数
                num_lines = len(re.findall(r'^\d+\s*$', srt_content, re.MULTILINE))
                logger.info(f"[DeepSeek] 字幕生成成功，共 {num_lines} 条，已保存到 {output_path}")
                return True
            else:
                logger.warning(f"[DeepSeek] 第 {attempt} 次返回内容不是合法 SRT，重试...")
                last_error = "返回内容不是合法SRT格式"

        except requests.exceptions.Timeout:
            last_error = "请求超时"
            logger.warning(f"[DeepSeek] 第 {attempt} 次请求超时，2秒后重试...")
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            last_error = f"网络错误: {e}"
            logger.warning(f"[DeepSeek] 第 {attempt} 次网络错误: {e}，2秒后重试...")
            time.sleep(2)
        except (KeyError, json.JSONDecodeError) as e:
            last_error = f"响应解析错误: {e}"
            logger.warning(f"[DeepSeek] 第 {attempt} 次响应解析错误: {e}，2秒后重试...")
            time.sleep(2)
        except Exception as e:
            last_error = f"未知错误: {e}"
            logger.warning(f"[DeepSeek] 第 {attempt} 次未知错误: {e}，2秒后重试...")
            time.sleep(2)

    # 所有重试都失败，降级为正则分句
    logger.error(f"[DeepSeek] 所有重试均失败（{last_error}），降级为正则分句")
    generate_srt_regex(text, total_duration, output_path)
    return False
