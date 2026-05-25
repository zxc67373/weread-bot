#!/usr/bin/env python3
"""
微信读书自动阅读机器人 - 简化版入口
基于原始项目逻辑，接受命令行参数
"""
import asyncio
import argparse
import logging
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from weread_bot.app import WeReadApplication
from weread_bot.config import WeReadConfig, ReadingConfig, NetworkConfig, NotificationConfig, LoggingConfig
from weread_bot.config_manager import ConfigManager


def main():
    parser = argparse.ArgumentParser(description="微信读书自动阅读机器人")
    parser.add_argument("-c", "--curl", default="curl_command.txt", help="CURL命令文件")
    parser.add_argument("-t", "--target", default="60", help="目标时长(分钟)")
    parser.add_argument("-i", "--interval", default="30", help="请求间隔(秒)")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    # 设置日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # 加载CURL配置
    curl_file = args.curl
    if not os.path.exists(curl_file):
        logging.error(f"CURL文件不存在: {curl_file}")
        return 1

    with open(curl_file, "r", encoding="utf-8") as f:
        curl_content = f.read().strip()

    # 创建配置对象
    config = WeReadConfig()
    config.curl_file_path = curl_file
    config.curl_content = curl_content
    config.startup_mode = "immediate"

    # 配置阅读参数
    config.reading = ReadingConfig()
    config.reading.target_duration = f"{args.target}"
    config.reading.reading_interval = f"{args.interval}"
    config.reading.mode = "smart_random"

    # 简化网络配置
    config.network = NetworkConfig()
    config.network.timeout = 30
    config.network.retry_times = 3

    # 关闭通知
    config.notification = NotificationConfig()
    config.notification.enabled = False

    # 日志配置
    config.logging = LoggingConfig()
    config.logging.level = "DEBUG" if args.verbose else "INFO"
    config.logging.console = True
    config.logging.file = ""

    logging.info(f"加载CURL: {args.curl}")
    logging.info(f"目标: {args.target}分钟, 间隔: {args.interval}秒")

    # 运行应用
    async def run():
        app = WeReadApplication(config)
        await app.run()

    try:
        asyncio.run(run())
        return 0
    except KeyboardInterrupt:
        logging.info("用户中断，程序退出")
        return 0
    except Exception as e:
        logging.error(f"程序异常: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())