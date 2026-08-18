"""
日志系统模块
统一配置 logging，同时输出到控制台和文件
分级别：DEBUG、INFO、WARNING、ERROR
"""
import os
import sys
import logging
from datetime import datetime

from config import config

# 日志目录
LOG_DIR = os.path.join(config.BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件名：run_20260817_143022.log
log_filename = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
log_filepath = os.path.join(LOG_DIR, log_filename)

# 日志格式
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 配置根 logger
logger = logging.getLogger("ad_auto")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # 不向上传递，避免重复输出

# 控制台处理器（INFO及以上，输出到stdout避免PowerShell误判为错误）
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
logger.addHandler(console_handler)

# 文件处理器（DEBUG及以上，记录更详细）
file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
logger.addHandler(file_handler)


def get_logger():
    """获取全局 logger 实例"""
    return logger


def info(msg: str):
    """INFO级别日志"""
    logger.info(msg)


def debug(msg: str):
    """DEBUG级别日志（只写文件，不输出控制台）"""
    logger.debug(msg)


def warning(msg: str):
    """WARNING级别日志"""
    logger.warning(msg)


def error(msg: str):
    """ERROR级别日志"""
    logger.error(msg)
