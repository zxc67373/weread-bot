import logging
import sys
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

from .config import LoggingConfig


def setup_logging(logging_config: LoggingConfig = None, verbose: bool = False):
    """设置日志系统"""
    if logging_config is None:
        logging_config = LoggingConfig()

    # 创建日志目录
    log_file_path = Path(logging_config.file)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # 设置日志级别
    if verbose:
        log_level = logging.DEBUG
    else:
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        log_level = level_map.get(logging_config.level.upper(), logging.INFO)

    # 设置日志格式
    format_map = {
        "simple": "%(levelname)s - %(message)s",
        "detailed": "%(asctime)s - %(levelname)-8s - %(message)s",
        "json": '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
    }
    log_format = format_map.get(logging_config.format, format_map["detailed"])

    # 设置处理器
    handlers = []

    # 控制台处理器
    if logging_config.console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(console_handler)

    # 文件处理器（支持轮转）
    try:
        max_bytes = _parse_size(logging_config.max_size)
        file_handler = RotatingFileHandler(
            logging_config.file,
            maxBytes=max_bytes,
            backupCount=logging_config.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    except Exception as e:
        file_handler = logging.FileHandler(logging_config.file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
        print(f"⚠️ 日志轮转设置失败，使用普通文件处理器: {e}")

    # 配置根日志记录器
    # Python 3.8+ 支持 force 参数，Python 3.7 需要手动处理
    basic_config_args = {
        "level": log_level,
        "format": log_format,
        "handlers": handlers,
    }

    # Python 3.8+ 支持 force 参数
    if sys.version_info >= (3, 8):
        basic_config_args["force"] = True

    logging.basicConfig(**basic_config_args)

    # 创建自定义print函数，同时输出到控制台和日志文件
    _setup_print_redirect(log_file_path)


def _parse_size(size_str: str) -> int:
    """解析大小字符串，如 '10MB' -> 10485760 bytes"""
    size_str = size_str.upper()
    if size_str.endswith("KB"):
        return int(size_str[:-2]) * 1024
    elif size_str.endswith("MB"):
        return int(size_str[:-2]) * 1024 * 1024
    elif size_str.endswith("GB"):
        return int(size_str[:-2]) * 1024 * 1024 * 1024
    else:
        return int(size_str)


def _setup_print_redirect(log_file_path: Path):
    """设置print重定向到日志文件"""
    import builtins
    
    # 保存原始print函数
    original_print = builtins.print

    def custom_print(*args, **kwargs):
        """自定义print函数，同时输出到控制台和日志文件"""
        # 输出到控制台
        original_print(*args, **kwargs)
        
        # 写入到日志文件
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                output = " ".join(str(arg) for arg in args) if args else ""
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] {output}\n")
                f.flush()
        except Exception:
            pass  # 静默失败，避免影响程序运行

    # 重写print为自定义print
    builtins.print = custom_print
