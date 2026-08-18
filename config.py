"""
全局配置模块
从 config.yaml 读取配置，支持多套配置切换
用法：
  from config import config
  config.OUTPUT_SUBDIR  # 访问配置
"""
import os
import yaml


class AppConfig:
    """应用全局配置类，从YAML文件读取"""

    def __init__(self, config_path: str = None):
        # 默认配置文件路径
        if config_path is None:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

        self._config_path = config_path
        self._load_from_yaml()
        self._init_derived_paths()

    def _load_from_yaml(self):
        """从YAML文件加载配置"""
        if not os.path.exists(self._config_path):
            raise FileNotFoundError(f"配置文件不存在：{self._config_path}")

        with open(self._config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 基础路径
        self.BASE_DIR = data.get("base_dir", r"D:\ad_auto")

        # 输出配置
        self.OUTPUT_SUBDIR = data.get("output_subdir", "默认项目")

        # 视频参数
        self.SPEED_RATE = data.get("speed_rate", 2.0)
        self.TARGET_RESOLUTION = data.get("target_resolution", "1080:1920")
        self.TARGET_FPS = data.get("target_fps", 30)
        # 编码器配置
        self.VIDEO_ENCODER = data.get("video_encoder", "libx264")  # libx264 或 h264_nvenc
        self.X264_CRF = data.get("x264_crf", 23)
        self.ENCODE_PRESET = data.get("encode_preset", "fast")
        self.NVENC_PRESET = data.get("nvenc_preset", "p4")
        self.NVENC_CQ = data.get("nvenc_cq", 23)

        # 贴纸参数
        self.STICKER_ALPHA = data.get("sticker_alpha", 0.08)
        self.STICKER_SCALE = data.get("sticker_scale", 0.05)
        self.STICKER_COUNT = data.get("sticker_count", 4)

        # 去重参数
        self.DEDUP_ALPHA = data.get("dedup_alpha", 0.03)

        # 滤镜参数
        self.NUM_RANDOM_FILTERS = data.get("num_random_filters", 2)
        self.FILTER_BLEND_OPACITY = data.get("filter_blend_opacity", 0.02)

        # TTS参数
        self.TTS_VOICE = data.get("tts_voice", "zh-CN-XiaoxiaoNeural")
        self.TTS_RATE = data.get("tts_rate", "+0%")
        self.TTS_VOLUME = data.get("tts_volume", "+0%")
        self.TTS_MAX_RETRIES = data.get("tts_max_retries", 3)

        # 文件名约定
        self.TTS_TEXT_FILE = data.get("tts_text_file", "sub1.txt")
        self.SUBTITLE_SRT_FILE = data.get("subtitle_srt_file", "caption.srt")
        self.SUBTITLE_PARAM_FILE = data.get("subtitle_param_file", "filter_parameter.txt")

        # NVENC可用性检测：如果配置了h264_nvenc但驱动不支持，自动降级为libx264
        if self.VIDEO_ENCODER == "h264_nvenc" and not self._check_nvenc_available():
            print("[警告] NVIDIA NVENC不可用（驱动版本过旧，需610.00+），自动降级为libx264 CPU编码")
            print("[提示] 请更新NVIDIA显卡驱动以启用硬件加速，速度可提升5-10倍")
            self.VIDEO_ENCODER = "libx264"

    def _check_nvenc_available(self) -> bool:
        """检测NVENC硬件编码器是否可用（跑一帧测试视频）"""
        import subprocess
        try:
            test_cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=128x128:d=1",
                "-c:v", "h264_nvenc", "-preset", "p4", "-f", "null", "-"
            ]
            result = subprocess.run(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def _init_derived_paths(self):
        """初始化基于BASE_DIR的派生路径"""
        # 素材目录
        self.RAW_VIDEO_DIR = os.path.join(self.BASE_DIR, "raw_clips")
        self.DEDUP_DIR = os.path.join(self.BASE_DIR, "dedup_videos")
        self.FILTER_LIB_DIR = os.path.join(self.BASE_DIR, "filter_lib")
        self.STICKER_DIR = os.path.join(self.BASE_DIR, "sticker_lib")
        self.SUBTITLE_DIR = os.path.join(self.BASE_DIR, "subtitles")
        self.TEMP_DIR = os.path.join(self.BASE_DIR, "temp")

        # 库目录
        self.VOICE_LIB_DIR = os.path.join(self.BASE_DIR, "voice_lib")
        self.VOICE_LIB_FILE = os.path.join(self.VOICE_LIB_DIR, "voices.txt")
        self.FONT_LIB_DIR = os.path.join(self.BASE_DIR, "font_lib")

        # 字体文件名 → 字体名映射（libass通过字体名查找，不是文件名）
        self.FONT_NAME_MAP = {
            "simhei.ttf": "SimHei",           # 黑体
            "simkai.ttf": "KaiTi",            # 楷体
            "simfang.ttf": "FangSong",        # 仿宋
            "SIMLI.TTF": "LiSu",              # 隶书
            "SIMYOU.TTF": "YouYuan",          # 幼圆
            "STCAIYUN.TTF": "STCaiyun",       # 华文彩云
            "STLITI.TTF": "STLiti",           # 华文隶书
            "STKAITI.TTF": "STKaiti",         # 华文楷体
            "STXIHEI.TTF": "STXihei",         # 华文细黑
            "STSONG.TTF": "STSong",           # 华文宋体
            "STFANGSO.TTF": "STFangsong",     # 华文仿宋
        }

    @property
    def OUTPUT_DIR(self):
        """最终输出目录，动态根据输出子目录名生成：output/子目录名/"""
        return os.path.join(self.BASE_DIR, "output", self.OUTPUT_SUBDIR)

    def get_video_encode_args(self) -> list:
        """
        根据配置的编码器返回FFmpeg视频编码参数列表
        libx264: [-c:v, libx264, -preset, fast, -crf, 23]
        h264_nvenc: [-c:v, h264_nvenc, -preset, p4, -cq, 23]
        用法：ffmpeg_cmd.extend(config.get_video_encode_args())
        """
        if self.VIDEO_ENCODER == "h264_nvenc":
            return [
                "-c:v", "h264_nvenc",
                "-preset", self.NVENC_PRESET,
                "-cq", str(self.NVENC_CQ),
            ]
        else:
            return [
                "-c:v", "libx264",
                "-preset", self.ENCODE_PRESET,
                "-crf", str(self.X264_CRF),
            ]

    def reload(self):
        """重新加载配置文件（运行时修改YAML后调用）"""
        self._load_from_yaml()
        self._init_derived_paths()


# 全局单例，其他模块通过 from config import config 使用
config = AppConfig()
