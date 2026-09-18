"""Pure application configuration loading.

Importing this module never probes FFmpeg, creates directories, or opens log
files. The executable entry point loads and binds a configuration explicitly.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read the small KEY=VALUE subset needed by this project."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


class AppConfig:
    """Application settings loaded without runtime side effects."""

    def __init__(self, config_path: str | None = None, environ: Mapping[str, str] | None = None):
        if config_path is None:
            config_path = str(Path(__file__).with_name("config.yaml"))
        loaded = self.from_file(config_path, environ=environ)
        self.__dict__.update(loaded.__dict__)

    @classmethod
    def from_file(
        cls,
        config_path: str,
        environ: Mapping[str, str] | None = None,
    ) -> "AppConfig":
        path = Path(config_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"配置文件不存在：{path}")

        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"配置文件顶层必须是对象：{path}")

        env = _read_dotenv(path.with_name(".env"))
        env.update(dict(os.environ if environ is None else environ))

        instance = cls.__new__(cls)
        instance._config_path = str(path)
        instance._apply(data, env)
        instance.validate()
        return instance

    def _apply(self, data: dict[str, Any], env: Mapping[str, str]) -> None:
        config_dir = Path(self._config_path).parent

        def resolve_path(value: str | os.PathLike[str], base: Path) -> str:
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = base / candidate
            return str(candidate.resolve())

        self.BASE_DIR = resolve_path(str(data.get("base_dir", ".")), config_dir)
        self.OUTPUT_SUBDIR = str(data.get("output_subdir", "默认项目"))

        self.SPEED_RATE = float(data.get("speed_rate", 2.0))
        self.TARGET_RESOLUTION = str(data.get("target_resolution", "1080:1920"))
        self.TARGET_FPS = int(data.get("target_fps", 30))
        self.VIDEO_ENCODER = str(data.get("video_encoder", "libx264"))
        self.X264_CRF = int(data.get("x264_crf", 23))
        self.ENCODE_PRESET = str(data.get("encode_preset", "fast"))
        self.NVENC_PRESET = str(data.get("nvenc_preset", "p4"))
        self.NVENC_CQ = int(data.get("nvenc_cq", 23))

        self.STICKER_ALPHA = float(data.get("sticker_alpha", 0.08))
        self.STICKER_SCALE = float(data.get("sticker_scale", 0.05))
        self.STICKER_COUNT = int(data.get("sticker_count", 4))
        self.DEDUP_ALPHA = float(data.get("dedup_alpha", 0.03))
        self.NUM_RANDOM_FILTERS = int(data.get("num_random_filters", 2))
        self.FILTER_BLEND_OPACITY = float(data.get("filter_blend_opacity", 0.02))

        self.TTS_VOICE = str(data.get("tts_voice", "zh-CN-XiaoxiaoNeural"))
        self.TTS_RATE = str(data.get("tts_rate", "+0%"))
        self.TTS_VOLUME = str(data.get("tts_volume", "+0%"))
        self.TTS_MAX_RETRIES = int(data.get("tts_max_retries", 3))

        self.TTS_TEXT_FILE = str(data.get("tts_text_file", "sub1.txt"))
        self.SUBTITLE_SRT_FILE = str(data.get("subtitle_srt_file", "caption.srt"))
        self.SUBTITLE_PARAM_FILE = str(data.get("subtitle_param_file", "filter_parameter.txt"))

        # Secrets only come from the process environment or an ignored .env file.
        self.DEEPSEEK_API_KEY = str(env.get("DEEPSEEK_API_KEY", "")).strip()
        self.DEEPSEEK_BASE_URL = str(data.get("deepseek_base_url", "https://api.deepseek.com"))
        self.DEEPSEEK_MODEL = str(data.get("deepseek_model", "deepseek-chat"))
        self.DEEPSEEK_MAX_RETRIES = int(data.get("deepseek_max_retries", 3))
        self.DEEPSEEK_MAX_CHARS_PER_LINE = int(data.get("deepseek_max_chars_per_line", 15))
        self.SUBTITLE_MODE = str(data.get("subtitle_mode", "deepseek"))
        self.SUBTITLE_MAX_CHARS_PER_LINE = int(data.get("subtitle_max_chars_per_line", 12))
        self.SUBTITLE_DOWN_RATIO = float(data.get("subtitle_down_ratio", 0.235))
        self.SUBTITLE_FONT_SIZE = int(data.get("subtitle_font_size", 15))

        self.LOCATIONS_FILE = resolve_path(
            str(data.get("locations_file", "地区.xlsx")), Path(self.BASE_DIR)
        )
        facts_file = str(data.get("facts_file", "facts.yaml"))
        self.FACTS_FILE = resolve_path(facts_file, Path(self.BASE_DIR))
        self.LOCATION_ROW = int(data.get("location_row", 1))
        self.COPY_TARGET_CHARS = int(data.get("copy_target_chars", 110))
        self.COPY_MAX_RETRIES = int(data.get("copy_max_retries", 3))
        self.TTS_PROVIDER = str(data.get("tts_provider", "edge"))
        self.TTS_CACHE = bool(data.get("tts_cache", True))
        self.PERSON_DETECTION_ENABLED = bool(data.get("person_detection_enabled", True))
        self.PERSON_MODEL = str(data.get("person_model", "yolo11n.pt"))
        self.PERSON_CONFIDENCE = float(data.get("person_confidence", 0.35))
        self.PERSON_SAMPLE_FPS = float(data.get("person_sample_fps", 2.0))
        self.PERSON_INTERVAL_GAP = float(data.get("person_interval_gap", 0.75))
        self.PERSON_MIN_INTERVAL = float(data.get("person_min_interval", 0.5))
        self.PREFERRED_SPEED = float(data.get("preferred_speed", data.get("speed_rate", 2.0)))
        self.MINIMUM_SPEED = float(data.get("minimum_speed", 1.0))
        self.SUPPLIED_SCRIPT = None

        self.JIANYING_DRAFT_ENABLED = bool(data.get("jianying_draft_enabled", True))
        self.JIANYING_DRAFT_NAME = str(data.get("jianying_draft_name", "editable"))
        self.BATCH_MAX_RETRIES = int(data.get("batch_max_retries", 2))

        self.RAW_VIDEO_DIR = os.path.join(self.BASE_DIR, "raw_clips")
        self.DEDUP_DIR = os.path.join(self.BASE_DIR, "dedup_videos")
        self.FILTER_LIB_DIR = os.path.join(self.BASE_DIR, "filter_lib")
        self.STICKER_DIR = os.path.join(self.BASE_DIR, "sticker_lib")
        self.SUBTITLE_DIR = os.path.join(self.BASE_DIR, "subtitles")
        self.TEMP_DIR = os.path.join(self.BASE_DIR, "temp")
        self.OUTPUT_ROOT = os.path.join(self.BASE_DIR, "output")
        self.VOICE_LIB_DIR = os.path.join(self.BASE_DIR, "voice_lib")
        self.VOICE_LIB_FILE = os.path.join(self.VOICE_LIB_DIR, "voices.txt")
        self.FONT_LIB_DIR = os.path.join(self.BASE_DIR, "font_lib")

        self.FONT_NAME_MAP = {
            "simhei.ttf": "SimHei",
            "simkai.ttf": "KaiTi",
            "simfang.ttf": "FangSong",
            "simli.ttf": "LiSu",
            "simyou.ttf": "YouYuan",
            "stcaiyun.ttf": "STCaiyun",
            "stliti.ttf": "STLiti",
            "stkaiti.ttf": "STKaiti",
            "stxihei.ttf": "STXihei",
            "stsong.ttf": "STSong",
            "stfangso.ttf": "STFangsong",
        }

    def validate(self) -> None:
        if self.SPEED_RATE <= 0:
            raise ValueError("speed_rate 必须大于 0")
        if self.TARGET_FPS <= 0:
            raise ValueError("target_fps 必须大于 0")
        if self.STICKER_COUNT < 0:
            raise ValueError("sticker_count 不能小于 0")
        if self.VIDEO_ENCODER not in {"libx264", "h264_nvenc"}:
            raise ValueError("video_encoder 仅支持 libx264 或 h264_nvenc")
        if not 0 < self.MINIMUM_SPEED <= self.PREFERRED_SPEED:
            raise ValueError("minimum_speed 必须大于0且不能超过 preferred_speed")
        if self.PREFERRED_SPEED > 2.0:
            raise ValueError("preferred_speed 不能超过 2.0")
        if self.LOCATION_ROW < 1:
            raise ValueError("location_row 必须从 1 开始")
        if not 0 < self.PERSON_CONFIDENCE <= 1:
            raise ValueError("person_confidence 必须在 0 到 1 之间")
        if self.SUBTITLE_MAX_CHARS_PER_LINE < 1:
            raise ValueError("subtitle_max_chars_per_line 必须大于 0")
        if not 0 <= self.SUBTITLE_DOWN_RATIO < 1:
            raise ValueError("subtitle_down_ratio 必须在 0 到 1 之间")
        if self.SUBTITLE_FONT_SIZE < 1:
            raise ValueError("subtitle_font_size 必须大于 0")
        if self.JIANYING_DRAFT_NAME != "editable":
            raise ValueError("当前 jianying_draft_name 必须为 editable")
        if self.BATCH_MAX_RETRIES < 0:
            raise ValueError("batch_max_retries 不能小于 0")

    @property
    def OUTPUT_DIR(self) -> str:
        return os.path.join(self.OUTPUT_ROOT, self.OUTPUT_SUBDIR)

    def get_video_encode_args(self) -> list[str]:
        if self.VIDEO_ENCODER == "h264_nvenc":
            return [
                "-c:v", "h264_nvenc",
                "-preset", self.NVENC_PRESET,
                "-cq", str(self.NVENC_CQ),
            ]
        return [
            "-c:v", "libx264",
            "-preset", self.ENCODE_PRESET,
            "-crf", str(self.X264_CRF),
        ]


class ConfigProxy:
    """Stable import target that can be bound once bootstrap has loaded config."""

    def __init__(self) -> None:
        object.__setattr__(self, "_value", None)

    @property
    def is_bound(self) -> bool:
        return object.__getattribute__(self, "_value") is not None

    def bind(self, value: AppConfig) -> None:
        object.__setattr__(self, "_value", value)

    def __getattr__(self, name: str):
        value = object.__getattribute__(self, "_value")
        if value is None:
            raise RuntimeError("应用配置尚未绑定，请先调用 config.bind(AppConfig.from_file(...))")
        return getattr(value, name)

    def __setattr__(self, name: str, value) -> None:
        current = object.__getattribute__(self, "_value")
        if current is None:
            raise RuntimeError("应用配置尚未绑定")
        setattr(current, name, value)


config = ConfigProxy()
