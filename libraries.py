"""
随机库模块
四大随机库：音色库、字体库、滤镜库、贴纸库
每个函数负责加载对应库文件 + 随机抽取
"""
import os
import random

from config import config
from logger import logger
from utils import get_target_files


def pick_random_voice() -> tuple:
    """
    从音色库随机选一个音色
    返回：(音色ID, 说明)
    """
    if not os.path.exists(config.VOICE_LIB_FILE):
        logger.info(f"音色库文件不存在：{config.VOICE_LIB_FILE}，使用默认音色 {config.TTS_VOICE}")
        return config.TTS_VOICE, "默认音色"
    voices = []
    with open(config.VOICE_LIB_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                vid, desc = line.split("|", 1)
                voices.append((vid.strip(), desc.strip()))
            else:
                voices.append((line, "未知音色"))
    if not voices:
        logger.info("音色库为空，使用默认音色")
        return config.TTS_VOICE, "默认音色"
    selected = random.choice(voices)
    logger.info(f"随机选中音色：{selected[0]}（{selected[1]}）")
    return selected


def pick_random_font() -> str:
    """
    从字体库随机选一个字体
    返回：字体名（如 SimHei）
    注意：libass 通过字体名查找，不是文件名，所以需要 FONT_NAME_MAP 映射
    """
    if not os.path.isdir(config.FONT_LIB_DIR):
        logger.info("字体库目录不存在，使用默认字体 SimHei")
        return "SimHei"
    # 扫描字体库，匹配 FONT_NAME_MAP 中的字体
    available_fonts = []
    for fname in os.listdir(config.FONT_LIB_DIR):
        key = fname.lower()
        if key.endswith((".ttf", ".otf")) and key in config.FONT_NAME_MAP:
            available_fonts.append(config.FONT_NAME_MAP[key])
    if not available_fonts:
        logger.info("字体库中无可用字体，使用默认字体 SimHei")
        return "SimHei"
    selected = random.choice(available_fonts)
    logger.info(f"随机选中字体：{selected}")
    return selected


def load_random_filters(num_filters: int) -> list:
    """
    从滤镜库随机选N个滤镜配置
    返回：[(文件名, 滤镜参数字符串), ...]
    """
    filter_files = get_target_files(config.FILTER_LIB_DIR, ".txt")
    if len(filter_files) == 0:
        logger.info("滤镜库为空，不应用滤镜")
        return []
    num = min(num_filters, len(filter_files))
    selected = random.sample(filter_files, num)
    filters = []
    for f_path in selected:
        with open(f_path, "r", encoding="utf-8") as fp:
            content = fp.read().strip()
            if content:
                filters.append((os.path.basename(f_path), content))
    logger.info(f"从滤镜库随机选中{len(filters)}个滤镜：")
    for name, _ in filters:
        logger.info(f"  - {name}")
    return filters


def pick_random_stickers(count: int = None) -> list:
    """
    从贴纸库随机选N张透明PNG贴纸
    返回：贴纸绝对路径列表
    """
    if count is None:
        count = config.STICKER_COUNT
    if count < 0:
        raise ValueError("贴纸数量不能小于 0")
    if count == 0:
        logger.info("贴纸数量为0，本次不添加贴纸")
        return []
    sticker_list = get_target_files(config.STICKER_DIR, ".png")
    if len(sticker_list) < count:
        raise ValueError(
            f"{config.STICKER_DIR} 内PNG贴纸不足{count}张，当前仅有{len(sticker_list)}张"
        )
    selected = random.sample(sticker_list, count)
    logger.info(f"随机选中{count}张贴纸：")
    for s in selected:
        logger.info(f"  - {os.path.basename(s)}")
    return selected
