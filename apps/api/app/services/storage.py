"""原始文件落盘。

为什么要有这一层：摄取失败后用户要能重跑（可能只是没配 embedding key）。
不存原始文件就只能让用户重新上传一次。

存哪、怎么命名：
- 目录来自配置 ``source_upload_dir``
- 文件名是 **uuid4 十六进制 + 净化后的扩展名**，绝不用用户上传的原名——
  原名可能有 ``../``、可能有中文、可能超长、可能撞车

W3 换 S3/MinIO 时只改本文件，调用方仍按「写进去 / 读出来」两个函数用。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import get_settings

# 只保留字母数字与点，其余（含路径分隔符）全替换掉。
_UNSAFE = re.compile(r"[^A-Za-z0-9.]")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB


class StorageError(Exception):
    """文件读写失败。"""


class UploadTooLarge(StorageError):
    """超过大小上限。"""


def _safe_suffix(filename: str) -> str:
    """从上传文件名提取扩展名，净化后返回（不含点，最多 10 字符）。"""
    suffix = Path(filename).suffix
    cleaned = _UNSAFE.sub("", suffix)
    return cleaned[:10]


def save_upload(payload: bytes, original_name: str) -> str:
    """写入上传文件，返回相对路径。

    相对而不是绝对——换机器部署时绝对路径全废。
    """
    if len(payload) > MAX_UPLOAD_BYTES:
        raise UploadTooLarge(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限")

    directory = Path(get_settings().source_upload_dir)
    directory.mkdir(parents=True, exist_ok=True)

    name = f"{uuid.uuid4().hex}{_safe_suffix(original_name)}"
    target = directory / name
    target.write_bytes(payload)
    return name


def read_upload(relative_path: str) -> bytes:
    """读回已存文件。路径来自数据库，不接受用户输入。"""
    directory = Path(get_settings().source_upload_dir)
    target = directory / Path(relative_path).name  # .name 挡住 ../ 穿越
    if not target.is_file():
        raise StorageError("原始文件不存在，可能已被清理")
    return target.read_bytes()


def delete_upload(relative_path: str) -> None:
    """删除原始文件。不存在不算错误——重跑摄取时可能已删过。"""
    directory = Path(get_settings().source_upload_dir)
    target = directory / Path(relative_path).name
    target.unlink(missing_ok=True)
