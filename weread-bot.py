#!/usr/bin/env python3
"""
微信读书自动阅读机器人 - 入口脚本
兼容原始脚本名称，实际逻辑已模块化到 weread_bot 包
"""
import asyncio
import sys


def main():
    """主入口函数"""
    try:
        # 导入并运行模块化的主程序
        from weread_bot.app import main as app_main
        asyncio.run(app_main())
    except ImportError as e:
        print(f"❌ 模块导入失败: {e}")
        print("请确保已安装所有依赖: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
