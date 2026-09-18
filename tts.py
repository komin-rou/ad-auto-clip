"""
TTS语音合成模块
封装 edge-tts 调用，含网络波动自动重试
"""
import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from config import config
from errors import TransientPipelineError
from logger import logger


@dataclass(frozen=True)
class SpeechBoundary:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class TTSResult:
    audio_path: str
    duration: float
    boundaries: tuple[SpeechBoundary, ...]
    provider: str = "edge"
    cache_hit: bool = False


def _is_transient_tts_error(error: BaseException) -> bool:
    if isinstance(error, (ValueError, FileNotFoundError, PermissionError)):
        return False
    if isinstance(error, (TransientPipelineError, TimeoutError, ConnectionError)):
        return True
    type_names = " ".join(cls.__name__.lower() for cls in type(error).__mro__)
    return any(token in type_names for token in (
        "timeout", "connection", "connector", "disconnected",
        "clienterror", "clientresponse", "serverconnection",
        "noaudio", "serviceunavailable",
    ))


def _tts_cache_key(text: str, voice: str) -> str:
    payload = "|".join((text, voice, config.TTS_RATE, config.TTS_VOLUME, "edge-v1"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def generate_tts_result(
    text: str,
    output_path: str,
    voice: str | None = None,
    max_retries: int | None = None,
    cache_dir: str | None = None,
    communicator_factory=None,
    duration_reader=None,
) -> TTSResult:
    """Stream Edge audio and word boundaries, with an optional durable cache."""
    from utils import get_audio_duration

    voice = voice or config.TTS_VOICE
    max_retries = max_retries or config.TTS_MAX_RETRIES
    if communicator_factory is None:
        import edge_tts
        communicator_factory = edge_tts.Communicate
    duration_reader = duration_reader or get_audio_duration
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cache_audio = cache_meta = None
    if cache_dir:
        root = Path(cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        key = _tts_cache_key(text, voice)
        cache_audio = root / f"{key}.mp3"
        cache_meta = root / f"{key}.json"
        if cache_audio.is_file() and cache_meta.is_file():
            payload = json.loads(cache_meta.read_text(encoding="utf-8"))
            shutil.copy2(cache_audio, output)
            boundaries = tuple(SpeechBoundary(**item) for item in payload["boundaries"])
            return TTSResult(str(output), float(payload["duration"]), boundaries, cache_hit=True)

    last_error = None
    for attempt in range(1, max_retries + 1):
        boundaries = []
        try:
            communicator = communicator_factory(
                text, voice, rate=config.TTS_RATE, volume=config.TTS_VOLUME
            )
            with output.open("wb") as audio_file:
                async for event in communicator.stream():
                    if event.get("type") == "audio":
                        audio_file.write(event.get("data", b""))
                    elif event.get("type") == "WordBoundary":
                        start = float(event.get("offset", 0)) / 10_000_000
                        duration = float(event.get("duration", 0)) / 10_000_000
                        boundaries.append(SpeechBoundary(str(event.get("text", "")), start, start + duration))
            if not output.is_file() or output.stat().st_size == 0:
                raise TransientPipelineError("TTS 未返回音频数据")
            duration = float(duration_reader(str(output)))
            result = TTSResult(str(output), duration, tuple(boundaries))
            if cache_audio and cache_meta:
                shutil.copy2(output, cache_audio)
                cache_meta.write_text(json.dumps({
                    "duration": duration,
                    "boundaries": [item.__dict__ for item in boundaries],
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        except Exception as exc:
            if output.exists():
                output.unlink()
            if not _is_transient_tts_error(exc):
                raise
            last_error = exc
            logger.warning("TTS生成失败（第%s/%s次）：%s", attempt, max_retries, exc)
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
    raise TransientPipelineError(
        f"TTS语音生成失败，已重试{max_retries}次：{last_error}"
    ) from last_error


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
    await generate_tts_result(text, output_path, voice=voice, max_retries=max_retries)
