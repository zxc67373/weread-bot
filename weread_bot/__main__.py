"""
允许使用 python -m weread_bot 运行应用
"""
import asyncio
from .app import main

if __name__ == "__main__":
    asyncio.run(main())
