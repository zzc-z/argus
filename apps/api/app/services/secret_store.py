"""凭据加密：Fernet 加密 + 解密。

## 为什么密钥要加密存

凭据表里存的是**能直接花钱的 API key**。明文存的话，一次库文件泄露
（备份、误提交、容器镜像层）就等于所有 key 一次性暴露——而且没有
「哪把 key 什么时候泄露的」可查。

## 用 Fernet 而不是手写 AES

``cryptography`` 已经在依赖里（``pyproject.toml`` 的间接依赖）。Fernet
是它的对称加密原语，自带两个我们需要的性质：

- **认证加密**——密文被篡改会解密失败（抛 ``InvalidToken``），而不是
  返回一段垃圾。手写 AES-CBC 没有这个性质，改一个 bit 就能把密文
  换成攻击者想要的内容。
- **自带 IV 与时间戳**——同一个明文加密两次得到不同密文（Fernet 里
  那个时间戳是明文可见的，但不影响解密）。

## 主密钥从哪来

**优先读环境变量 ``CREDENTIALS_ENCRYPTION_KEY``；没配就读本地文件
``apps/api/.credentials.key``；还没有就自动生成一份写进去。**

这个顺序抄的是 n8n——最接近本项目场景的自托管项目（凭据存数据库、
单机部署、多人用同一个实例）：

    n8n 官方文档：「If you never set it, n8n generates a random key on
    first launch and writes it to ``~/.n8n/config``.」

    Password Pusher 的故障表把这件事的后果写成了症状：
    「Users logged out after container restart |
      Random key generated on each start」

**为什么必须持久化到文件而不是每次启动现生成**：key 每次变，库里所有
密文就都解不开了——用户配的 key 全部失效，且没有任何报错。这是
Password Pusher 列为头号故障的那一类。

**为什么环境变量只是「可选覆盖」**：多实例/容器编排时 worker 必须
共享同一把 key（n8n 在队列模式下有同样的要求），那时用环境变量
或 ``_FILE`` 挂载更合适。单人本地跑不需要——自动生成的那份够用。

**不复用 ``JWT_SECRET_KEY``**：那个密钥会为了踢掉旧会话而轮换，
轮换后所有存量密文都解不开，等于把整库凭据报废。

## key 文件与库文件的关系（重要）

key 文件默认就在 ``apps/api/``——和 ``argus.db`` 同一个目录。

这意味着**两份文件一起被拷走，加密等于没做**。加密真正防住的是：
SQL 注入拖库、备份工具导出、``.db`` 被误提交进 git。

n8n 的安全文档也是这么说的：「A backup of ``~/.n8n`` taken together
with the database is a complete credential dump」——所以真正的生产
部署要把 key 放进 secrets manager 或用 ``_FILE`` 挂载。

对本项目（给测试人员用的多账号环境）这个取舍是合适的：零配置，
而真正的威胁（数据库被 dump）被挡住了。

⚠️ **备份时必须连 ``.credentials.key`` 一起备份**——只备份库的话，
凭据全部不可恢复。

## 密文格式

前缀 ``enc:v1:`` + Fernet 密文。

前缀的作用是**能识别出「这列还没加密」**——加加密之前写的明文行
（历史数据）仍然能读出来。加前缀而不是靠「能不能解密」来判，是因为
Fernet 解密失败有两种原因：真的加密过但密钥不对，或者压根是明文。
前缀把第二种情况明确标出来，报错信息才指向正确的原因。
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# 密文前缀。见模块 docstring 的「密文格式」。
CIPHER_PREFIX = "enc:v1:"


class SecretCryptoError(RuntimeError):
    """加密或解密失败。"""


class SecretDecryptError(SecretCryptoError):
    """密文解不开——主密钥不对，或密文被篡改。"""


def _key_file_path() -> Path:
    """key 文件的位置：``apps/api/.credentials.key``。

    **与 ``argus.db`` 同目录**——跟着数据一起活，一起备份。

    路径相对本文件算起（``app/services/`` → 上两级是 ``apps/api/``），
    不是相对进程 cwd——cwd 会因启动方式而变（uvicorn 在仓库根跑、
    在 apps/api 跑，路径就不同了）。
    """
    return Path(__file__).resolve().parents[2] / ".credentials.key"


def _load_or_create_key() -> tuple[str, str]:
    """取主密钥：**环境变量 → key 文件 → 自动生成写文件**。

    返回 ``(密钥, 来源)``——来源是 ``"env"`` / ``"file"`` / ``"generated"``。

    ## 为什么连来源一起返回

    密钥无效时的错误信息必须指对**是哪一档出的问题**：
    环境变量配错了 vs key 文件被写坏了，是两件不同的事，处置也不同
    （前者改配置，后者恢复备份）。

    只看「文件存不存在」判断是不够的：环境变量配了个无效值、
    同时 key 文件恰好存在，就会报成「文件坏了」——指错了方向。
    """
    # 1. 环境变量优先——多实例/容器编排时用它共享同一把 key。
    #    延迟 import：``app.config`` 导入 ``app.models``，而模型层要
    #    import 本模块——顶层 import 会形成环。
    from app.config import get_settings

    raw = get_settings().credentials_encryption_key
    if raw:
        # 配置项声明成 ``SecretStr``——它既不是 str 也不是 bytes，
        # 直接喂给 Fernet 会抛 TypeError。必须先取明文再编码。
        if hasattr(raw, "get_secret_value"):
            return raw.get_secret_value(), "env"
        if isinstance(raw, str):
            return raw, "env"
        raise SecretCryptoError(
            "CREDENTIALS_ENCRYPTION_KEY 类型不对——它必须是字符串或 SecretStr"
        )

    # 2. key 文件。
    path = _key_file_path()
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        if content:
            return content, "file"
        # 文件存在但**空的** → 拒绝，不自动重生成。
        #
        # ⚠️ 这里曾经是「当没配，继续生成一份」——**那是错的**。
        #
        # 文件空 = 原来的 key 没了（被误清空 / 被截断 / 写盘失败）。
        # 此时自动生成一把新 key 并**覆盖**文件，存量密文就**永久**失效
        # ——且只有一条 info 日志，没人知道发生过什么。
        #
        # 这正是本模块 docstring 引的 Password Pusher 头号故障
        # （*Random key generated on each start* → 重启后所有密文
        # 解不开）。**报错拒绝启动**才是对的：用户看到「主密钥文件是空的，
        # 库里已存的密文解不开了」，于是知道要从备份恢复它。
        #
        # 不覆盖文件是关键——报错时文件保持原样，用户恢复备份的内容
        # 写回去就能继续。
        raise SecretCryptoError(
            f"凭据加密主密钥文件 {path} 存在但是空的。"
            "**库里已存的密文用原来的 key 才解得开**——"
            "请从备份恢复这个文件（它与 argus.db 要一起备份），"
            "或用环境变量 CREDENTIALS_ENCRYPTION_KEY 指定原来的那把。"
            "程序**不会**自动生成新 key——那会让存量密文永久失效。"
        )

    # 3. 自动生成并写盘。
    key = Fernet.generate_key().decode("ascii")
    stored = _write_key_file(path, key)
    if stored != key:
        # 另一个进程抢先写入了，用它那把——两边才能互相解密。
        return stored, "file"
    logger.info("已生成凭据加密主密钥：%s（请与数据库一起备份）", path)
    return key, "generated"


def _write_key_file(path: Path, key: str) -> str:
    """把主密钥写进文件（权限 0600），返回**最终落盘的那把** key。

    ## 为什么不能覆盖已有文件

    冷启动时多个进程可能同时走到这里（多 worker、后端与脚本同时首次运行），
    各自生成一把 key。若后写的一方覆盖先写的，先写那一方已经用自己的 key
    加密入库的密文就永久解不开。

    所以落盘用 ``os.link``：目标已存在时它直接失败（原子的「不存在才创建」），
    这时改读已有的那把并返回，调用方用它。``replace`` 做不到这一点——它会覆盖。

    ## 为什么先写临时文件

    直接写目标文件，中途崩溃会留下半截内容，下次启动被当成有效 key 读进去。
    临时文件用 ``mkstemp`` 取唯一名，多个进程不会写到同一个临时文件上。
    """
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key)
        tmp_path.chmod(0o600)
        try:
            os.link(tmp_path, path)
        except FileExistsError:
            return path.read_text(encoding="utf-8").strip()
        return key
    except OSError as exc:
        raise SecretCryptoError(
            f"无法写入凭据加密主密钥文件 {path}：{exc}。"
            "可以改用环境变量 CREDENTIALS_ENCRYPTION_KEY 提供主密钥。"
        ) from exc
    finally:
        # 无论成败都删掉临时文件：成功时目标文件已通过硬链接持有同一份内容；
        # 失败时留着它，下次启动会多出一把没人知道的 key。
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def is_encrypted(value: str | None) -> bool:
    """这个值是不是加密存的（带前缀）。"""
    return value is not None and value.startswith(CIPHER_PREFIX)


def _fernet() -> Fernet:
    """取 Fernet 实例。

    **每次调用都重建**——Fernet 对象不可变且轻量，而主密钥的解析
    （读文件或生成）不该每次都做。
    """
    key_str, source = _load_or_create_key()
    try:
        return Fernet(key_str.encode())
    except (ValueError, TypeError) as exc:
        # **错误信息要指向真正的问题。**
        #
        # 「格式不对」听起来像用户配错了，而实际更常见的是「key 文件
        # 写坏了，库里已存的密文从此解不开」——那需要恢复备份，不是改
        # 一行配置。按**来源**分两种说法（见 `_load_or_create_key`）：
        # 环境变量配错 vs 文件写坏，是两件不同的事。
        if source == "file":
            path = _key_file_path()
            raise SecretCryptoError(
                f"凭据加密主密钥文件 {path} 的内容不是有效的 Fernet 密钥"
                "（文件可能被截断或手动改过）。"
                "**库里已存的密文用这把 key 解不开了**——需要从备份恢复它，"
                "或者用环境变量 CREDENTIALS_ENCRYPTION_KEY 指定原来的那把。"
            ) from exc
        if source == "env":
            raise SecretCryptoError(
                "环境变量 CREDENTIALS_ENCRYPTION_KEY 的值不是有效的 Fernet 密钥"
                "（32 字节 urlsafe base64）。"
                "**库里已存的密文用这把 key 解不开了**——确认它与写入时的是同一把。"
            ) from exc
        if source == "generated":
            # 自动生成的那把不该格式错——生成出来的一定合法。
            # 真走到这里说明 Fernet 本身出了问题（极不可能），但错误信息
            # 要指得准。
            raise SecretCryptoError(
                "自动生成的凭据加密主密钥不是有效的 Fernet 密钥——这是 Fernet 库"
                "本身的问题，请检查 cryptography 的版本。"
            ) from exc
        raise SecretCryptoError(
            "凭据加密主密钥格式不对——它必须是 Fernet 生成的 base64 密钥"
            "（32 字节 urlsafe base64）。生成："
            "python3 -c \"from cryptography.fernet import Fernet;"
            " print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt_secret(plaintext: str | None) -> str | None:
    """加密一个明文。**None / 空串原样返回 None。**

    归一在这里做（空串 → None）而不是留给调用方：空串是「配了但没填」，
    加密它会得到一段有值的密文，回显时显示成「已配置」但实际调不通。
    """
    if plaintext is None:
        return None
    stripped = plaintext.strip()
    if not stripped:
        return None
    token = _fernet().encrypt(stripped.encode("utf-8")).decode("ascii")
    return f"{CIPHER_PREFIX}{token}"


def decrypt_secret(ciphertext: str | None) -> str | None:
    """解密。**不是加密存的值原样返回**（兼容加密前写入的历史数据）。

    解密失败时抛 :class:`SecretDecryptError`——**不返回 None**。
    返回 None 与「没配」无法区分，调用方会当成「用户没配」而回落到
    部署默认，用的是一把错的 key 去调，错误信息会指向别处。

    历史明文数据**保持可用即可**——本项目不提供重写脚本；那些行会在
    用户下次保存该字段时被重新加密（写入路径一律走加密）。
    """
    if ciphertext is None:
        return None
    stripped = ciphertext.strip()
    if not stripped:
        return None
    if not is_encrypted(stripped):
        # 加密之前写入的历史数据——原样返回。
        return stripped
    token = stripped[len(CIPHER_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptError(
            "凭据密文解不开——CREDENTIALS_ENCRYPTION_KEY 与写入时不一致，"
            "或密文已被篡改"
        ) from exc


__all__ = [
    "CIPHER_PREFIX",
    "SecretCryptoError",
    "SecretDecryptError",
    "decrypt_secret",
    "encrypt_secret",
    "is_encrypted",
]
