"""
TTS语音合成模块
封装 edge-tts 调用，含网络波动自动重试
"""
import asyncio
import edge_tts

from config import config
from logger import logger


async def generate_tts(text: str, output_path: str, voice: str = None, max_retries: int = None):
    """
    用 edge-tts 生成语音文件
    含自动重试机制：edge-tts 偶尔 NoAudioReceived 是网络波动，重试即可
    采用指数退避：第1次等2秒，第2次等4秒，第3次等8秒
    :param text: 要朗读的文本
    :param output_path: 输出音频路径
    :param voice: 音色ID，默认用 config.TTS_VOICE
    :param max_retries: 最大重试次数，默认用 config.TTS_MAX_RETRIES
    """
    if voice is None:
        voice = config.TTS_VOICE
    if max_retries is None:
        max_retries = config.TTS_MAX_RETRIES

    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(
                text, voice,
                rate=config.TTS_RATE,
                volume=config.TTS_VOLUME
            )
            await communicate.save(output_path)
            return  # 成功直接返回
        except Exception as e:
            logger.info(f"TTS生成失败（第{attempt + 1}/{max_retries}次尝试）：{e}")
            if attempt < max_retries - 1:
                # 指数退避：第1次等2秒，第2次等4秒，第3次等8秒
                wait_seconds = 2 ** (attempt + 1)
                logger.info(f"{wait_seconds}秒后自动重试（指数退避）...")
                await asyncio.sleep(wait_seconds)

    # 所有重试都失败
    raise RuntimeError(f"TTS语音生成失败，已重试{max_retries}次，请检查网络连接")
