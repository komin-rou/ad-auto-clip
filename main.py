"""Command-line entry point for one isolated video-generation job."""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

from config import AppConfig, config
from logger import configure_logging, logger


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="广告视频自动化混剪")
    parser.add_argument("--config", help="YAML 配置文件路径")
    parser.add_argument("--job", help="任务名；默认使用配置中的 output_subdir")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="删除并重建同名任务的 temp/output 子目录",
    )
    parser.add_argument("--locations", help="地点 Excel 文件路径")
    parser.add_argument("--location-row", type=int, help="地点数据行，从 1 开始")
    parser.add_argument("--facts", help="固定事实库 YAML 路径")
    parser.add_argument("--script", help="直接使用给定文案并跳过 AI 生成")
    parser.add_argument(
        "--no-person-detection", action="store_true",
        help="调试模式：把全部素材视为有人物",
    )
    parser.add_argument("--scan-resources", action="store_true", help="扫描并写出本地资源清单")
    parser.add_argument(
        "--jianying-compat-test", action="store_true",
        help="检查 --job 指定任务的剪映草稿结构",
    )
    parser.add_argument("--all-locations", action="store_true", help="处理地点 Excel 中全部地点")
    parser.add_argument("--resume", action="store_true", help="从已有任务断点继续")
    parser.add_argument("--max-retries", type=int, help="批量瞬时错误最大重试次数")
    return parser.parse_args(argv)


def run_batch_command(app_config, args, pipeline_factory=None) -> int:
    from batch_runner import BatchOptions, run_batch
    from location_loader import load_locations

    locations = load_locations(app_config.LOCATIONS_FILE)
    if pipeline_factory is None:
        from pipeline import VideoPipeline

        def pipeline_factory(row_number):
            app_config.LOCATION_ROW = row_number
            return VideoPipeline()

    options = BatchOptions(
        output_root=Path(app_config.OUTPUT_ROOT),
        jobs_root=Path(app_config.TEMP_DIR) / "jobs",
        max_retries=(
            app_config.BATCH_MAX_RETRIES if args.max_retries is None else args.max_retries
        ),
        resume=args.resume,
        overwrite=args.overwrite,
    )
    report = run_batch(locations, pipeline_factory, options)
    output_root = Path(app_config.OUTPUT_ROOT)
    json_path = report.write_json(output_root / "batch_report.json")
    csv_path = report.write_csv(output_root / "batch_report.csv")
    logger.info("批量报告：%s；%s", json_path, csv_path)
    return 1 if any(item.status == "failed" for item in report.items) else 0


def main(argv=None) -> int:
    args = parse_args(argv)
    default_config = Path(__file__).with_name("config.yaml")
    config_path = Path(args.config).resolve() if args.config else default_config

    app_config = AppConfig.from_file(str(config_path))
    if args.locations:
        app_config.LOCATIONS_FILE = str(Path(args.locations).resolve())
    if args.location_row is not None:
        if args.location_row < 1:
            raise ValueError("--location-row 必须从 1 开始")
        app_config.LOCATION_ROW = args.location_row
    if args.facts:
        app_config.FACTS_FILE = str(Path(args.facts).resolve())
    app_config.SUPPLIED_SCRIPT = args.script
    if args.no_person_detection:
        app_config.PERSON_DETECTION_ENABLED = False
    config.bind(app_config)
    configure_logging(app_config.BASE_DIR)

    if args.scan_resources:
        from resource_catalog import scan_resource_catalog, write_resource_catalog
        manifest_path = Path(app_config.BASE_DIR) / "resource_manifest.json"
        write_resource_catalog(scan_resource_catalog(app_config), manifest_path)
        logger.info("资源清单：%s", manifest_path)
        return 0

    if args.jianying_compat_test:
        if not args.job:
            raise ValueError("--jianying-compat-test 必须同时提供 --job")
        from jianying_draft import validate_draft_structure, write_compatibility_report
        draft_dir = Path(app_config.OUTPUT_ROOT) / args.job / "jianying_draft" / "editable"
        report = validate_draft_structure(draft_dir)
        report_path = Path(app_config.OUTPUT_ROOT) / args.job / "jianying_compatibility.json"
        write_compatibility_report(report, report_path)
        logger.info("剪映兼容检查：%s；报告：%s", report.status, report_path)
        return 0 if report.passed else 1

    if args.all_locations:
        return run_batch_command(app_config, args)

    # Keep every ordinary run different, as requested.
    random.seed(time.time_ns() ^ os.getpid())

    from pipeline import VideoPipeline

    if args.job:
        output_name = args.job
    else:
        from location_loader import load_location
        output_name = load_location(app_config.LOCATIONS_FILE, app_config.LOCATION_ROW).full_name
    logger.info("===== 任务：%s =====", output_name)
    try:
        pipeline = VideoPipeline()
        pipeline.run(output_name, overwrite=args.overwrite, resume=args.resume)
    except Exception as exc:
        logger.error("处理失败：%s", exc)
        return 1

    logger.info("处理完成：output/%s/", output_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
