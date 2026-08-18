"""
广告视频自动化混剪程序 — 入口文件
用法：
  python main.py                  # 生成视频（输出目录由config.yaml的output_subdir决定）
  python main.py --config xxx.yaml # 使用指定配置文件
"""
import os
import sys
import random
import time

from config import config, AppConfig


def parse_args():
    """解析命令行参数"""
    args = {
        "config_path": None,
    }
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--config" and i + 1 < len(sys.argv):
            args["config_path"] = sys.argv[i + 1]
            i += 1
        i += 1
    return args


if __name__ == "__main__":
    cli_args = parse_args()

    # 如果指定了配置文件，重新加载配置
    if cli_args["config_path"]:
        config_path = cli_args["config_path"]
        if not os.path.isabs(config_path):
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_path)
        print(f"使用配置文件：{config_path}")
        config.__init__(config_path)

    # 显式初始化随机种子，用纳秒级时间+进程ID，确保每次运行随机性不同
    random.seed(time.time_ns() ^ os.getpid())

    # 延迟导入，确保config加载完成后再导入依赖config的模块
    from pipeline import VideoPipeline

    output_name = config.OUTPUT_SUBDIR
    print(f"===== 输出目录：{output_name} =====")

    pipeline = VideoPipeline()

    try:
        pipeline.run(output_name)
        print(f"\n✅ 处理完成！成品在 output/{output_name}/")
    except Exception as e:
        print(f"\n❌ 处理失败：{e}")
