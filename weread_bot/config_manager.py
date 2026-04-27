import os
import json
import logging
from pathlib import Path
from typing import Any, List
import yaml

from .config import (
    WeReadConfig, ReadingConfig, NetworkConfig, HumanSimulationConfig,
    NotificationConfig, NotificationChannel, HackConfig, ScheduleConfig,
    DaemonConfig, LoggingConfig, UserConfig, BookInfo, ChapterInfo,
    SmartRandomConfig
)


class ConfigManager:
    """配置管理器 - 负责从YAML和环境变量加载配置"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> WeReadConfig:
        """加载配置文件"""
        config_data = {}

        # 尝试加载YAML配置文件
        if Path(self.config_path).exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config_data = yaml.safe_load(f) or {}
                print(f"✅ 已加载配置文件: {self.config_path}")
            except Exception as e:
                logging.warning(f"⚠️ 配置文件加载失败: {e}")

        # 创建主配置对象
        config = WeReadConfig(
            startup_mode=self._get_config_value(
                config_data, "app.startup_mode", "STARTUP_MODE", "immediate"
            ),
            startup_delay=self._get_config_value(
                config_data, "app.startup_delay", "STARTUP_DELAY", "1-10"
            ),
            max_concurrent_users=int(
                self._get_config_value(
                    config_data, "app.max_concurrent_users", "MAX_CONCURRENT_USERS", "1"
                )
            ),
            curl_file_path=self._get_config_value(
                config_data, "curl_config.file_path", "WEREAD_CURL_BASH_FILE_PATH", ""
            ),
            curl_content=self._get_config_value(
                config_data, "curl_config.content", "WEREAD_CURL_STRING", ""
            ),
            users=self._load_user_configs(config_data),
        )

        # 加载阅读配置
        config.reading = ReadingConfig(
            mode=self._get_config_value(
                config_data, "reading.mode", "READING_MODE", "smart_random"
            ),
            target_duration=self._get_config_value(
                config_data, "reading.target_duration", "TARGET_DURATION", "60-70"
            ),
            reading_interval=self._get_config_value(
                config_data, "reading.reading_interval", "READING_INTERVAL", "25-35"
            ),
            use_curl_data_first=self._get_bool_config(
                config_data, "reading.use_curl_data_first", "USE_CURL_DATA_FIRST", True
            ),
            fallback_to_config=self._get_bool_config(
                config_data, "reading.fallback_to_config", "FALLBACK_TO_CONFIG", True
            ),
            books=self._load_books(config_data),
            smart_random=SmartRandomConfig(
                book_continuity=float(
                    self._get_config_value(
                        config_data,
                        "reading.smart_random.book_continuity",
                        "BOOK_CONTINUITY",
                        "0.8",
                    )
                ),
                chapter_continuity=float(
                    self._get_config_value(
                        config_data,
                        "reading.smart_random.chapter_continuity",
                        "CHAPTER_CONTINUITY",
                        "0.7",
                    )
                ),
                book_switch_cooldown=int(
                    self._get_config_value(
                        config_data,
                        "reading.smart_random.book_switch_cooldown",
                        "BOOK_SWITCH_COOLDOWN",
                        "300",
                    )
                ),
            ),
        )

        # 加载网络配置
        config.network = NetworkConfig(
            timeout=int(
                self._get_config_value(
                    config_data, "network.timeout", "NETWORK_TIMEOUT", "30"
                )
            ),
            retry_times=int(
                self._get_config_value(
                    config_data, "network.retry_times", "RETRY_TIMES", "3"
                )
            ),
            retry_delay=self._get_config_value(
                config_data, "network.retry_delay", "RETRY_DELAY", "5-15"
            ),
            rate_limit=int(
                self._get_config_value(
                    config_data, "network.rate_limit", "RATE_LIMIT", "10"
                )
            ),
        )

        # 加载人类行为模拟配置
        config.human_simulation = HumanSimulationConfig(
            enabled=self._get_bool_config(
                config_data,
                "human_simulation.enabled",
                "HUMAN_SIMULATION_ENABLED",
                False,
            ),
            reading_speed_variation=self._get_bool_config(
                config_data,
                "human_simulation.reading_speed_variation",
                "READING_SPEED_VARIATION",
                True,
            ),
            break_probability=float(
                self._get_config_value(
                    config_data,
                    "human_simulation.break_probability",
                    "BREAK_PROBABILITY",
                    "0.1",
                )
            ),
            break_duration=self._get_config_value(
                config_data,
                "human_simulation.break_duration",
                "BREAK_DURATION",
                "10-20",
            ),
            rotate_user_agent=self._get_bool_config(
                config_data,
                "human_simulation.rotate_user_agent",
                "ROTATE_USER_AGENT",
                False,
            ),
        )

        # 加载通知配置
        config.notification = NotificationConfig(
            enabled=self._get_bool_config(
                config_data, "notification.enabled", "NOTIFICATION_ENABLED", True
            ),
            include_statistics=self._get_bool_config(
                config_data,
                "notification.include_statistics",
                "INCLUDE_STATISTICS",
                True,
            ),
            channels=self._load_notification_channels(config_data),
        )

        # 加载hack配置
        config.hack = HackConfig(
            cookie_refresh_ql=self._get_bool_config(
                config_data, "hack.cookie_refresh_ql", "HACK_COOKIE_REFRESH_QL", False
            ),
        )

        # 加载调度配置
        config.schedule = ScheduleConfig(
            enabled=self._get_bool_config(
                config_data, "schedule.enabled", "SCHEDULE_ENABLED", False
            ),
            cron_expression=self._get_config_value(
                config_data,
                "schedule.cron_expression",
                "CRON_EXPRESSION",
                "0 */2 * * *",
            ),
            timezone=self._get_config_value(
                config_data, "schedule.timezone", "TIMEZONE", "Asia/Shanghai"
            ),
        )

        # 加载守护进程配置
        config.daemon = DaemonConfig(
            enabled=self._get_bool_config(
                config_data, "daemon.enabled", "DAEMON_ENABLED", False
            ),
            session_interval=self._get_config_value(
                config_data, "daemon.session_interval", "SESSION_INTERVAL", "120-180"
            ),
            max_daily_sessions=int(
                self._get_config_value(
                    config_data, "daemon.max_daily_sessions", "MAX_DAILY_SESSIONS", "12"
                )
            ),
        )

        # 加载日志配置
        config.logging = LoggingConfig(
            level=self._get_config_value(
                config_data, "logging.level", "LOG_LEVEL", "INFO"
            ),
            format=self._get_config_value(
                config_data, "logging.format", "LOG_FORMAT", "detailed"
            ),
            file=self._get_config_value(
                config_data, "logging.file", "LOG_FILE", "logs/weread.log"
            ),
            max_size=self._get_config_value(
                config_data, "logging.max_size", "LOG_MAX_SIZE", "10MB"
            ),
            backup_count=int(
                self._get_config_value(
                    config_data, "logging.backup_count", "LOG_BACKUP_COUNT", "5"
                )
            ),
            console=self._get_bool_config(
                config_data, "logging.console", "LOG_CONSOLE", True
            ),
        )

        config.max_concurrent_users = max(1, config.max_concurrent_users)
        return config

    def _load_books(self, config_data: dict) -> List[BookInfo]:
        """加载书籍配置"""
        books = []
        books_config = self._get_nested_dict_value(config_data, "reading.books")
        
        if books_config and isinstance(books_config, list):
            for book_data in books_config:
                if isinstance(book_data, dict):
                    name = book_data.get("name", "")
                    book_id = book_data.get("book_id", "")
                    chapters_config = book_data.get("chapters", [])

                    if name and book_id and isinstance(chapters_config, list):
                        chapters = []
                        chapter_infos = []

                        for chapter_item in chapters_config:
                            if isinstance(chapter_item, str):
                                chapters.append(chapter_item)
                                chapter_infos.append(ChapterInfo(chapter_id=chapter_item))
                            elif isinstance(chapter_item, dict):
                                chapter_id = chapter_item.get("chapter_id") or chapter_item.get("id")
                                chapter_index = chapter_item.get("chapter_index") or chapter_item.get("index")

                                if chapter_id:
                                    chapters.append(chapter_id)
                                    chapter_infos.append(
                                        ChapterInfo(
                                            chapter_id=chapter_id,
                                            chapter_index=chapter_index,
                                        )
                                    )

                        if chapters:
                            books.append(
                                BookInfo(
                                    name=name,
                                    book_id=book_id,
                                    chapters=chapters,
                                    chapter_infos=chapter_infos,
                                )
                            )
                            print(f"✅ 已加载书籍配置: {name} ({book_id}), 章节数: {len(chapters)}")

        if not books:
            print("ℹ️ 未配置书籍信息，将使用CURL数据或运行时动态添加")

        return books

    def _get_config_value(
        self, config_data: dict, yaml_path: str, env_key: str, default: Any
    ) -> Any:
        """获取配置值，优先级：环境变量 > YAML > 默认值"""
        env_value = os.getenv(env_key)
        if env_value:
            env_value = self._resolve_env_placeholders(env_value)
            return self._parse_config_value(env_value, type(default))

        yaml_value = self._get_nested_dict_value(config_data, yaml_path)
        if yaml_value is not None:
            yaml_value = self._resolve_env_placeholders(str(yaml_value))
            return self._parse_config_value(yaml_value, type(default))

        return default

    def _get_bool_config(
        self, config_data: dict, yaml_path: str, env_key: str, default: bool
    ) -> bool:
        """获取布尔类型配置值"""
        value = self._get_config_value(config_data, yaml_path, env_key, str(default))
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return default

    def _get_nested_dict_value(self, data: dict, path: str) -> Any:
        """从嵌套字典中获取值"""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    def _resolve_env_placeholders(self, value: str) -> str:
        """解析环境变量占位符"""
        import re
        pattern = r"\$\{([^}]+)\}"

        def replace_match(match):
            env_var = match.group(1)
            return os.getenv(env_var, match.group(0))

        return re.sub(pattern, replace_match, value)

    def _parse_config_value(self, value: str, target_type: type) -> Any:
        """解析配置值为指定类型"""
        if target_type == list:
            if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return []
            return []
        return value

    def _load_notification_channels(self, config_data: dict) -> List[NotificationChannel]:
        """加载通知通道配置"""
        channels = []

        channels_config = self._get_nested_dict_value(config_data, "notification.channels")
        if channels_config and isinstance(channels_config, list):
            for channel_data in channels_config:
                if isinstance(channel_data, dict):
                    channel_config = self._apply_env_overrides_to_channel(
                        channel_data.get("name"), channel_data.get("config", {})
                    )

                    channel = NotificationChannel(
                        name=channel_data.get("name"),
                        enabled=self._get_bool_config(
                            channel_data, "enabled", "ENABLED", True
                        ),
                        config=channel_config,
                    )
                    channels.append(channel)

        if not channels:
            channels = self._create_channels_from_env_vars()

        return channels

    def _apply_env_overrides_to_channel(self, channel_name: str, base_config: dict) -> dict:
        """应用环境变量覆盖到通道配置"""
        config = base_config.copy()

        if channel_name == "pushplus":
            if os.getenv("PUSHPLUS_TOKEN"):
                config["token"] = os.getenv("PUSHPLUS_TOKEN")

        elif channel_name == "telegram":
            if os.getenv("TELEGRAM_BOT_TOKEN"):
                config["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN")
            if os.getenv("TELEGRAM_CHAT_ID"):
                config["chat_id"] = os.getenv("TELEGRAM_CHAT_ID")

            proxy_config = config.get("proxy", {})
            if os.getenv("HTTP_PROXY"):
                proxy_config["http"] = os.getenv("HTTP_PROXY")
            if os.getenv("HTTPS_PROXY"):
                proxy_config["https"] = os.getenv("HTTPS_PROXY")
            if proxy_config:
                config["proxy"] = proxy_config

        elif channel_name == "wxpusher":
            if os.getenv("WXPUSHER_SPT"):
                config["spt"] = os.getenv("WXPUSHER_SPT")

        elif channel_name == "bark":
            if os.getenv("BARK_SERVER"):
                config["server"] = os.getenv("BARK_SERVER")
            if os.getenv("BARK_DEVICE_KEY"):
                config["device_key"] = os.getenv("BARK_DEVICE_KEY")

        # 可以继续添加其他通道...

        return config

    def _create_channels_from_env_vars(self) -> List[NotificationChannel]:
        """从环境变量自动创建通知通道"""
        channels = []

        if os.getenv("PUSHPLUS_TOKEN"):
            channels.append(
                NotificationChannel(
                    name="pushplus",
                    enabled=True,
                    config={"token": os.getenv("PUSHPLUS_TOKEN")},
                )
            )

        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            telegram_config = {
                "bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
                "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
            }
            proxy_config = {}
            if os.getenv("HTTP_PROXY"):
                proxy_config["http"] = os.getenv("HTTP_PROXY")
            if os.getenv("HTTPS_PROXY"):
                proxy_config["https"] = os.getenv("HTTPS_PROXY")
            if proxy_config:
                telegram_config["proxy"] = proxy_config

            channels.append(
                NotificationChannel(name="telegram", enabled=True, config=telegram_config)
            )

        if channels:
            print(f"✅ 从环境变量自动创建了 {len(channels)} 个通知通道")

        return channels

    def _load_user_configs(self, config_data: dict) -> List[UserConfig]:
        """加载用户配置"""
        users = []
        
        users_config = self._get_nested_dict_value(config_data, "curl_config.users")
        if users_config and isinstance(users_config, list):
            for user_data in users_config:
                if isinstance(user_data, dict) and user_data.get("name"):
                    user = UserConfig(
                        name=user_data.get("name"),
                        file_path=user_data.get("file_path", ""),
                        content=user_data.get("content", ""),
                        reading_overrides=user_data.get("reading_overrides", {}),
                    )
                    users.append(user)
                    print(f"✅ 已加载用户配置: {user.name}")

        # 回退：WEREAD_CURL_STRING 按至少两个空行拆分为多用户
        if not users:
            curl_env = os.getenv("WEREAD_CURL_STRING", "")
            if curl_env:
                import re
                segments = [
                    seg.strip()
                    for seg in re.split(r"(?:\r?\n\s*){2,}", curl_env)
                    if seg.strip()
                ]
                if len(segments) > 1:
                    for idx, seg in enumerate(segments, start=1):
                        users.append(UserConfig(name=f"env_user_{idx}", content=seg))
                    print(f"✅ 已从 WEREAD_CURL_STRING 拆分出 {len(users)} 个用户配置")
                elif segments:
                    users.append(UserConfig(name="env_user_1", content=segments[0]))

        return users
