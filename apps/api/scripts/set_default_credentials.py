"""写入共享默认凭据——全库一行，所有没自己配的用户共用。

开箱即用的落点：部署时跑一次这个脚本，把 API key 写进共享默认行
（**加密存储**），之后任何人登录都能直接用，不需要自己配。

## 为什么是命令行而不是页面

共享默认行是**全局**配置——改它会影响所有用户。项目里没有管理员
角色（用户表没有 role 列），所以「让任意登录用户能改全局配置」=
「任何注册用户都能改全站配置」。命令行脚本只有能操作服务器的人能跑。

## 用法

    cd apps/api
    .venv/bin/python scripts/set_default_credentials.py \
        --anthropic-key sk-ant-... \
        --anthropic-base-url https://llmapi.pro \
        --tavily-key tvly-... \
        --embedding-key sk-... \
        --embedding-base-url https://dashscope.aliyuncs.com/compatible-mode/v1

**只传要改的字段**——没传的字段保持原值（部分更新）。

**清空某一项用 `--clear`**——例如 ``--clear tavily_key``。
传空字符串（``--tavily-key ""``）**不会**清空：空串按「没传」跳过，
什么都不会写。这与后端接口的约定不同（那边空串也是「忽略」），
所以清空只能走 ``--clear``。

## 前置条件

**无。** 主密钥会自动生成到 ``apps/api/.credentials.key``
（见 ``app/services/secret_store.py``）——不需要配 ``.env``。

多实例部署时用 ``CREDENTIALS_ENCRYPTION_KEY`` 环境变量指定共享的
那把 key（各实例必须一致，否则一台写的密文另一台解不开）。

## key 不回显

脚本**不回显** key 的值，只说「写了哪些字段」。

⚠️ key 会进 shell 历史——所以别把真 key 直接写在命令行里。
用环境变量传（``--anthropic-key "$MY_KEY"``）能避开 shell 历史，
但环境变量同样会被子进程看到（``ps e``）。要彻底避开就把 key 写进
一个权限 0600 的文件，用 ``$(cat /path/to/key)`` 读出来。
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# 从仓库任意位置调用都能 import 到 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("LOG_LEVEL", "ERROR")
logging.disable(logging.CRITICAL)

from app.db import SessionLocal  # noqa: E402
from app.models.credentials import SCOPE_DEFAULT, ProviderCredentials  # noqa: E402
from app.services.secret_store import encrypt_secret  # noqa: E402

# key 字段 → 加密后写入。其余字段（base_url / 模型名）明文存。
SECRET_FIELDS = ("anthropic_api_key", "tavily_api_key", "embedding_api_key")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="写入共享默认凭据（加密存储，全库一行）",
    )
    parser.add_argument("--anthropic-key", help="Anthropic API key")
    parser.add_argument("--anthropic-base-url", help="Anthropic 中转站地址")
    parser.add_argument("--tavily-key", help="Tavily API key")
    parser.add_argument("--embedding-key", help="嵌入服务 API key")
    parser.add_argument("--embedding-base-url", help="嵌入服务 OpenAI 兼容端点")
    parser.add_argument(
        "--clear",
        action="append",
        default=[],
        metavar="FIELD",
        help="清空某个字段（可重复）。FIELD: anthropic_key / anthropic_base_url / "
        "tavily_key / embedding_key / embedding_base_url",
    )
    return parser.parse_args()


# 参数名 → (模型列名, 是否是 secret)
_FIELD_MAP = {
    "anthropic_key": ("anthropic_api_key", True),
    "anthropic_base_url": ("anthropic_base_url", False),
    "tavily_key": ("tavily_api_key", True),
    "embedding_key": ("embedding_api_key", True),
    "embedding_base_url": ("embedding_base_url", False),
}


async def main() -> int:
    args = parse_args()

    updates: dict[str, str | None] = {}

    # 先处理「清空」——显式优先于传值。
    for raw in args.clear:
        key = raw.strip()
        if key not in _FIELD_MAP:
            print(f"未知的字段名：{raw}", file=sys.stderr)
            print(f"可用：{', '.join(sorted(_FIELD_MAP))}", file=sys.stderr)
            return 2
        column, _ = _FIELD_MAP[key]
        updates[column] = None

    # 再处理传值——空串按「没传」跳过（不是清空）。
    #
    # **已被 `--clear` 指名的字段跳过**——「显式优先于传值」：
    # `--clear tavily_key --tavily-key sk-new` 时，清空优先，
    # 否则传值会在后面把它覆盖掉（--clear 就白写了）。
    for arg_name, (column, is_secret) in _FIELD_MAP.items():
        if column in updates:
            continue
        value = getattr(args, arg_name, None)
        if value is None:
            continue
        stripped = value.strip()
        if not stripped:
            continue
        updates[column] = encrypt_secret(stripped) if is_secret else stripped

    if not updates:
        print("没有要写入的字段。用 --help 看用法。")
        return 2

    async with SessionLocal() as db:
        row = await ProviderCredentials.find_default(db)
        if row is None:
            row = ProviderCredentials(user_id=None, scope=SCOPE_DEFAULT)
            db.add(row)
        for column, value in updates.items():
            setattr(row, column, value)
        await db.commit()

    # 不回显 key 的值——只说写了哪些字段。
    print(f"已写入共享默认凭据（{len(updates)} 项）：")
    for column in updates:
        print(f"  - {column}")
    print("提示：这些值加密存储，主密钥在 apps/api/.credentials.key（与数据库一起备份）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
