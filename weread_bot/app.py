import asyncio
import signal
import argparse
import logging
from datetime import datetime, timedelta
from typing import Set

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from croniter import croniter

from .config import WeReadConfig
from .config_manager import ConfigManager
from .logger import setup_logging
from .session import WeReadSessionManager
from .notification import NotificationService


class WeReadApplication:
    """微信读书应用程序管理器"""

    _instance = None
    _shutdown_requested = False
    _current_session_managers: Set[WeReadSessionManager] = set()
    _daily_session_count = 0
    _last_session_date = None

    def __init__(self, config: WeReadConfig):
        self.config = config
        WeReadApplication._instance = self

        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    @classmethod
    def get_instance(cls):
        """获取应用程序实例"""
        return cls._instance

    def _signal_handler(self, signum, frame):
        """信号处理器"""
        startup_mode = self.config.startup_mode.lower()

        if startup_mode == "immediate":
            print(f"📡 收到信号 {signum}，立即退出")
            import sys
            sys.exit(0)
        else:
            print(f"📡 收到信号 {signum}，准备优雅关闭...")
            WeReadApplication._shutdown_requested = True

            if WeReadApplication._current_session_managers:
                print(f"⏳ 正在等待 {len(WeReadApplication._current_session_managers)} 个会话完成...")

    async def run(self):
        """根据配置的启动模式运行应用程序"""
        startup_mode = self.config.startup_mode.lower()

        if startup_mode == "immediate":
            await self._run_immediate_mode()
        elif startup_mode == "scheduled":
            await self._run_scheduled_mode()
        elif startup_mode == "daemon":
            await self._run_daemon_mode()
        else:
            raise ValueError(f"未知的启动模式: {self.config.startup_mode}")

    async def _run_immediate_mode(self):
        """立即执行模式"""
        print("🚀 启动模式: 立即执行")
        await self.run_single_session()

    async def _run_scheduled_mode(self):
        """定时执行模式"""
        print("🚀 启动模式: 定时执行")

        if not self.config.schedule.enabled:
            logging.error("❌ 定时模式已启用，但schedule配置未启用")
            return

        timezone_name = self.config.schedule.timezone or "Asia/Shanghai"
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            logging.error(f"❌ 无效的时区配置: {timezone_name}")
            return

        try:
            cron_iter = croniter(self.config.schedule.cron_expression, datetime.now(tz))
        except Exception as e:
            logging.error(f"❌ 无效的cron表达式: {e}")
            return

        print(f"⏰ 定时任务已启动 (时区 {timezone_name})，表达式: {self.config.schedule.cron_expression}")

        while not WeReadApplication._shutdown_requested:
            next_run = cron_iter.get_next(datetime)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=tz)
            now = datetime.now(tz)
            wait_seconds = (next_run - now).total_seconds()

            if wait_seconds <= 0:
                continue

            print(f"🗓️ 下一次执行时间: {next_run.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S %Z')}")

            while wait_seconds > 0 and not WeReadApplication._shutdown_requested:
                await asyncio.sleep(min(wait_seconds, 1))
                now = datetime.now(tz)
                wait_seconds = (next_run - now).total_seconds()

            if WeReadApplication._shutdown_requested:
                break

            await self.run_single_session()

        print("👋 定时任务已停止")

    async def _run_daemon_mode(self):
        """守护进程模式"""
        print("🚀 启动模式: 守护进程")

        if not self.config.daemon.enabled:
            logging.error("❌ 守护进程模式已启用，但daemon配置未启用")
            return

        while not WeReadApplication._shutdown_requested:
            # 检查每日会话限制
            current_date = datetime.now().date()
            if WeReadApplication._last_session_date != current_date:
                WeReadApplication._daily_session_count = 0
                WeReadApplication._last_session_date = current_date

            if WeReadApplication._daily_session_count >= self.config.daemon.max_daily_sessions:
                print(f"📊 已达到每日最大会话数限制: {self.config.daemon.max_daily_sessions}")
                await self._wait_until_next_day()
                continue

            # 执行阅读会话
            try:
                await self.run_single_session()
                WeReadApplication._daily_session_count += 1

                # 如果没有请求关闭，等待下一次会话
                if not WeReadApplication._shutdown_requested:
                    from .utils import RandomHelper
                    interval_minutes = RandomHelper.get_random_int_from_range(
                        self.config.daemon.session_interval
                    )
                    print(f"😴 守护进程等待 {interval_minutes} 分钟后执行下一次会话...")

                    # 分段等待，以便能够响应关闭信号
                    for _ in range(interval_minutes * 60):
                        if WeReadApplication._shutdown_requested:
                            break
                        await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"❌ 守护进程会话执行失败: {e}")
                await asyncio.sleep(300)

        print("👋 守护进程已停止")

    async def _wait_until_next_day(self):
        """等待到第二天"""
        now = datetime.now()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow += timedelta(days=1)
        wait_seconds = (tomorrow - now).total_seconds()

        print(f"⏰ 等待到明天 00:00，剩余 {wait_seconds/3600:.1f} 小时")

        for _ in range(int(wait_seconds)):
            if WeReadApplication._shutdown_requested:
                break
            await asyncio.sleep(1)

    @classmethod
    async def run_single_session(cls):
        """执行单次阅读会话"""
        instance = cls.get_instance()
        if not instance:
            logging.error("❌ 应用程序实例未初始化")
            return

        # 检查是否配置了多用户模式
        if instance.config.users:
            await cls._run_multi_user_sessions(instance)
        else:
            await cls._run_single_user_session(instance)

    @classmethod
    async def _run_single_user_session(cls, instance):
        """执行单用户会话"""
        session_manager = None
        try:
            session_manager = WeReadSessionManager(instance.config)
            WeReadApplication._current_session_managers.add(session_manager)

            session_stats = await session_manager.start_reading_session()

            print("📊 会话统计:")
            print(session_stats.get_statistics_summary())

            # 发送通知
            if instance.config.notification.enabled and instance.config.notification.include_statistics:
                try:
                    notification_service = NotificationService(instance.config.notification)
                    await notification_service.send_notification_async(
                        session_stats.get_statistics_summary()
                    )
                except Exception as e:
                    logging.error(f"❌ 通知发送失败: {e}")

        except Exception as e:
            error_msg = f"❌ 阅读会话执行失败: {e}"
            logging.error(error_msg)

            try:
                notification_service = NotificationService(instance.config.notification)
                await notification_service.send_notification_async(error_msg)
            except Exception:
                pass
        finally:
            if session_manager:
                WeReadApplication._current_session_managers.discard(session_manager)

    @classmethod
    async def _run_multi_user_sessions(cls, instance):
        """执行多用户会话"""
        user_count = len(instance.config.users)
        print(f"🎭 检测到多用户配置，共 {user_count} 个用户")

        concurrency = max(1, instance.config.max_concurrent_users)
        if concurrency > user_count:
            concurrency = user_count
        print(f"⚙️  最大并发用户数: {concurrency}")

        semaphore = asyncio.Semaphore(concurrency)
        tasks = []

        async def run_for_user(user_config):
            if WeReadApplication._shutdown_requested:
                print("📡 收到关闭信号，跳过后续用户")
                return None

            async with semaphore:
                if WeReadApplication._shutdown_requested:
                    return None

                print(f"👤 开始执行用户 {user_config.name} 的阅读会话")
                session_manager = WeReadSessionManager(instance.config, user_config)
                WeReadApplication._current_session_managers.add(session_manager)

                try:
                    session_stats = await session_manager.start_reading_session()
                    print(f"📊 用户 {user_config.name} 会话统计:")
                    print(session_stats.get_statistics_summary())
                    return {"name": user_config.name, "stats": session_stats, "success": True}
                except Exception as e:
                    error_msg = f"❌ 用户 {user_config.name} 阅读会话执行失败: {e}"
                    logging.error(error_msg)
                    try:
                        notification_service = NotificationService(instance.config.notification)
                        await notification_service.send_notification_async(error_msg)
                    except Exception:
                        pass
                    return {"name": user_config.name, "stats": None, "success": False}
                finally:
                    WeReadApplication._current_session_managers.discard(session_manager)

        for user_config in instance.config.users:
            tasks.append(asyncio.create_task(run_for_user(user_config)))

        all_session_stats = []
        successful_users = []
        failed_users = []

        for task in asyncio.as_completed(tasks):
            result = await task
            if not result:
                continue
            if result["success"] and result["stats"]:
                all_session_stats.append((result["name"], result["stats"]))
                successful_users.append(result["name"])
            else:
                failed_users.append(result["name"])

        # 生成多用户会话总结
        await cls._generate_multi_user_summary(
            instance, all_session_stats, successful_users, failed_users
        )

    @classmethod
    async def _generate_multi_user_summary(
        cls, instance, all_session_stats, successful_users, failed_users
    ):
        """生成多用户会话总结"""
        total_users = len(instance.config.users)
        successful_count = len(successful_users)
        failed_count = len(failed_users)

        total_duration = sum(stats.actual_duration_seconds for _, stats in all_session_stats)
        total_reads = sum(stats.successful_reads for _, stats in all_session_stats)
        total_failed_reads = sum(stats.failed_reads for _, stats in all_session_stats)

        summary = f"""🎭 多用户阅读会话总结

👥 用户统计:
  📊 总用户数: {total_users}
  ✅ 成功用户: {successful_count} ({', '.join(successful_users) if successful_users else '无'})
  ❌ 失败用户: {failed_count} ({', '.join(failed_users) if failed_users else '无'})

📖 阅读统计:
  ⏱️ 总阅读时长: {total_duration // 60}分{total_duration % 60}秒
  ✅ 成功请求: {total_reads}次
  ❌ 失败请求: {total_failed_reads}次
  📈 整体成功率: {(total_reads / (total_reads + total_failed_reads) * 100) if (total_reads + total_failed_reads) > 0 else 0:.1f}%

🎉 多用户阅读任务完成！"""

        print("📊 多用户会话总结:")
        print(summary)

        if instance.config.notification.enabled and instance.config.notification.include_statistics:
            try:
                notification_service = NotificationService(instance.config.notification)
                await notification_service.send_notification_async(summary)
            except Exception as e:
                logging.error(f"❌ 多用户总结通知发送失败: {e}")


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="微信读书智能阅读机器人",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
启动模式说明:
  immediate  - 立即执行一次阅读会话后退出（默认）
  scheduled  - 根据cron表达式定时执行
  daemon     - 守护进程模式，持续运行并定期执行会话

示例:
  python -m weread_bot --mode immediate
  python -m weread_bot --mode scheduled
  python -m weread_bot --mode daemon
        """,
    )

    parser.add_argument(
        "--mode", "-m", choices=["immediate", "scheduled", "daemon"], help="启动模式"
    )
    parser.add_argument(
        "--config", "-c", default="config.yaml", help="配置文件路径 (默认: config.yaml)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="启用详细日志输出")

    return parser.parse_args()


async def main():
    """主函数"""
    args = parse_arguments()

    try:
        # 加载配置
        config_manager = ConfigManager(args.config)
        config = config_manager.config

        # 使用配置设置日志
        setup_logging(config.logging, verbose=args.verbose)

        # 命令行参数覆盖配置文件
        if args.mode:
            config.startup_mode = args.mode
            print(f"🔧 命令行参数覆盖启动模式: {args.mode}")

        # 打印启动信息
        print(f"\n📚 微信读书阅读机器人 v{config.version}")
        print(f"🚀 启动模式: {config.startup_mode}")
        print(f"📖 阅读模式: {config.reading.mode}")
        print(f"🎯 目标时长: {config.reading.target_duration} 分钟")
        print(f"👥 用户数量: {len(config.users) if config.users else 1}\n")

        # 创建并运行应用程序
        app = WeReadApplication(config)
        await app.run()

    except KeyboardInterrupt:
        print("\n👋 用户中断，程序退出")
    except Exception as e:
        error_msg = f"❌ 程序运行错误: {e}"
        logging.error(error_msg, exc_info=True)

        try:
            config_manager = ConfigManager(args.config if "args" in locals() else "config.yaml")
            notification_service = NotificationService(config_manager.config.notification)
            await notification_service.send_notification_async(error_msg)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
