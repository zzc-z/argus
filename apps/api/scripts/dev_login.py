"""开发调试用：生成一个已登录用户的 JWT。

本地联调时不必每次走一遍 GitHub OAuth——尤其是 GitHub 连不上的时候。

用法（token 走管道，不要回显到终端或对话里）：
    uv run python scripts/dev_login.py > /tmp/jwt.txt
    curl -H "Cookie: argus_session=$(cat /tmp/jwt.txt)" ...

必须在 apps/api 下运行：Settings 用 env_file=".env"（相对路径），
换个 cwd 就找不到配置了。在浏览器里测需要手动注入 HttpOnly cookie，
见 WORKLOG.md。
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# 从仓库任意位置调用都能 import 到 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# SQLAlchemy 的 echo 日志会把 SQL 打到 stdout，混进 token 里。
os.environ.setdefault("LOG_LEVEL", "ERROR")
logging.disable(logging.CRITICAL)

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.services.token import create_access_token

EMAIL = "dev@argus.local"


async def main() -> None:
    """确保有一个可登录用户，把他的 token 打到 stdout。"""
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == EMAIL))
        if user is None:
            user = User(email=EMAIL, display_name="Dev")
            db.add(user)
            await db.commit()
            await db.refresh(user)
        print(create_access_token(user.id))


asyncio.run(main())