"""
输出管理模块
负责输出子文件夹创建、随机参数记录文件写入
"""
import os

from config import config
from logger import logger
from utils import make_dir_safe


def ensure_output_dir(output_name: str) -> str:
    """
    确保输出目录存在，返回输出目录路径
    :param output_name: 输出子目录名
    :return: 输出目录绝对路径
    """
    # 临时修改 config 的输出子目录名，让 OUTPUT_DIR 动态指向对应目录
    config.OUTPUT_SUBDIR = output_name
    output_dir = config.OUTPUT_DIR
    make_dir_safe(output_dir)
    return output_dir


def write_params_record(output_dir: str, run_params: dict):
    """
    写入随机参数记录文件到输出目录
    :param output_dir: 输出目录路径
    :param run_params: 随机参数字典
    """
    params_file = os.path.join(output_dir, "随机参数记录.txt")
    with open(params_file, "w", encoding="utf-8") as f:
        f.write("=" * 50 + "\n")
        f.write("  广告视频随机参数记录\n")
        f.write("=" * 50 + "\n\n")
        for key, value in run_params.items():
            f.write(f"【{key}】\n")
            f.write(f"  {value}\n\n")
        f.write("=" * 50 + "\n")
        f.write("  最终成品视频：final_video_with_tts.mp4\n")
        f.write("=" * 50 + "\n")
    logger.info(f"\n随机参数已记录到：{params_file}")
    return params_file
