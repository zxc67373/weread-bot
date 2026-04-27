from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import platform
from pathlib import Path

VERSION = "0.3.6"
REPO = "https://github.com/funnyzak/weread-bot"


@dataclass
class NetworkConfig:
    """网络配置"""
    timeout: int = 30
    retry_times: int = 3
    retry_delay: str = "5-15"
    rate_limit: int = 10


@dataclass
class ChapterInfo:
    """章节信息"""
    chapter_id: str
    chapter_index: Optional[int] = None


@dataclass
class BookInfo:
    """书籍信息"""
    name: str
    book_id: str
    chapters: List[str] = field(default_factory=list)
    chapter_infos: List[ChapterInfo] = field(default_factory=list)


@dataclass
class SmartRandomConfig:
    """智能随机配置"""
    book_continuity: float = 0.8
    chapter_continuity: float = 0.7
    book_switch_cooldown: int = 300


@dataclass
class ScheduleConfig:
    """定时任务配置"""
    enabled: bool = False
    cron_expression: str = "0 */2 * * *"
    timezone: str = "Asia/Shanghai"


@dataclass
class DaemonConfig:
    """守护进程配置"""
    enabled: bool = False
    session_interval: str = "120-180"
    max_daily_sessions: int = 12


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    format: str = "detailed"
    file: str = "logs/weread.log"
    max_size: str = "10MB"
    backup_count: int = 5
    console: bool = True


@dataclass
class ReadingConfig:
    """阅读配置"""
    mode: str = "smart_random"
    target_duration: str = "60-70"
    reading_interval: str = "25-35"
    use_curl_data_first: bool = True
    fallback_to_config: bool = True
    books: List[BookInfo] = field(default_factory=list)
    smart_random: SmartRandomConfig = field(default_factory=SmartRandomConfig)


@dataclass
class HumanSimulationConfig:
    """人类行为模拟配置"""
    enabled: bool = True
    reading_speed_variation: bool = True
    break_probability: float = 0.15
    break_duration: str = "30-180"
    rotate_user_agent: bool = True


@dataclass
class UserConfig:
    """用户配置"""
    name: str
    file_path: str = ""
    content: str = ""
    reading_overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationChannel:
    """通知通道配置"""
    name: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationConfig:
    """通知配置"""
    enabled: bool = True
    include_statistics: bool = True
    channels: List[NotificationChannel] = field(default_factory=list)


@dataclass
class HackConfig:
    """Hack配置"""
    cookie_refresh_ql: bool = False


@dataclass
class WeReadConfig:
    """微信读书配置主类"""
    name: str = "WeReadBot"
    version: str = VERSION
    startup_mode: str = "immediate"
    startup_delay: str = "1-10"
    max_concurrent_users: int = 1
    curl_file_path: str = ""
    curl_content: str = ""
    users: List[UserConfig] = field(default_factory=list)
    reading: ReadingConfig = field(default_factory=ReadingConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    human_simulation: HumanSimulationConfig = field(default_factory=HumanSimulationConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    hack: HackConfig = field(default_factory=HackConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def get_startup_info(self) -> str:
        """获取启动信息摘要"""
        startup_info = f"""
📚 微信读书阅读机器人

应用信息:
  📱 应用名称: {self.name}
  🔢 版本: {self.version}
  📦 仓库: {REPO}
  🐍 Python版本: {platform.python_version()}
  🖥️  系统: {platform.system()} {platform.release()}
  📁 工作目录: {Path.cwd()}

运行配置:
  🚀 启动模式: {self._get_startup_mode_desc()}
  ⏰ 启动延迟: {self.startup_delay} 秒
  📖 阅读模式: {self._get_reading_mode_desc()}
  📊 目标时长: {self.reading.target_duration} 分钟
  🔄 阅读间隔: {self.reading.reading_interval} 秒
  🎭 人类模拟: {'启用' if self.human_simulation.enabled else '禁用'}
  👥 最大并发用户: {self.max_concurrent_users}

网络配置:
  ⏱️  超时时间: {self.network.timeout} 秒
  🔄 重试次数: {self.network.retry_times} 次
  📈 请求限制: {self.network.rate_limit} 请求/分钟

通知配置:
  📢 通知状态: {'启用' if self.notification.enabled else '禁用'}
  📨 通知通道: {len([c for c in self.notification.channels if c.enabled])} 个启用

数据源配置:
  👥 用户配置: {len(self.users)} 个用户 {'(多用户模式)' if self.users else '(单用户模式)'}
  📚 配置书籍: {len(self.reading.books)} 本

日志配置:
  📝 日志级别: {self.logging.level}
  💾 日志文件: {self.logging.file}
"""
        if self.startup_mode.lower() == "scheduled" and self.schedule.enabled:
            startup_info += f"\n⏰ 定时任务: {self.schedule.cron_expression} ({self.schedule.timezone})"

        if self.startup_mode.lower() == "daemon" and self.daemon.enabled:
            startup_info += f"\n🔄 守护进程: 会话间隔 {self.daemon.session_interval} 分钟，每日最大 {self.daemon.max_daily_sessions} 次会话"

        return startup_info

    def _get_startup_mode_desc(self) -> str:
        """获取启动模式描述"""
        mode_map = {
            "immediate": "立即执行",
            "scheduled": "定时执行",
            "daemon": "守护进程",
        }
        return mode_map.get(self.startup_mode.lower(), self.startup_mode)

    def _get_reading_mode_desc(self) -> str:
        """获取阅读模式描述"""
        mode_map = {
            "smart_random": "智能随机",
            "sequential": "顺序阅读",
            "pure_random": "纯随机",
        }
        return mode_map.get(self.reading.mode.lower(), self.reading.mode)

