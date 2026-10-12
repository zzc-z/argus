"""向量库接入层：sqlite-vec 扩展加载 + vec0 表的建表/写入/检索。

为什么不用 PRD 写的 pgvector：dev 环境没有 Postgres（无 Docker、5432 未开），
而检索逻辑要能真跑起来验证。检索调用全部收口在本模块，
将来换 pgvector 只改这里，调用方不动。

## 一个必须记住的坑

加载扩展**不能**用 SQLAlchemy 的 ``connect`` 事件。事件回调里拿到的
``dbapi_conn.driver_connection`` 是 ``aiosqlite.Connection``，它的
``enable_load_extension`` 是 **async** 方法。在同步回调里调用只会造一个
协程对象并被丢弃，扩展静默不加载——之后所有 ``vec_*`` 函数报
``no such function: vec_version``，且不报任何加载期错误。

唯一可行入口是 ``create_async_engine(async_creator=...)``：它在 async
上下文里建连接，能真正 await 加载。``connect`` 事件方案已实测失败。
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import aiosqlite
import sqlite_vec
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings

# ── 常量 ────────────────────────────────────────────────────
# embedding 维度必须与写入时的模型一致，改了要重建 vec0 表（维度写在建表 DDL 里）。
# 1536 = OpenAI text-embedding-3-small 的原始维度。不降维：512 维版本是
# PRD 早期估算，1536 检索质量更好，且 sqlite-vec 的 float[N] 存的是 float32。
EMBEDDING_DIM = 1536

VEC_TABLE = "chunk_embeddings"
CHUNK_TABLE = "document_chunks"


# ── 引擎构造 ────────────────────────────────────────────────
def _sqlite_path(url: str) -> str:
    """从 SQLAlchemy URL 里取出裸文件路径。

    ``sqlite+aiosqlite:///./argus.db`` → ``./argus.db``。
    async_creator 只能拿到文件路径，拿不到 ``sqlite+aiosqlite://`` 这种 URL。
    """
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise ValueError(
            f"向量库扩展只支持 SQLite，当前 database_url 是 {url.split('://')[0]}"
        )
    return url[len(prefix) :]


async def _open_with_extension(path: str) -> aiosqlite.Connection:
    """建一条已加载 sqlite-vec 的连接。

    必须在 async 函数里 await——见模块 docstring 里那个坑。
    """
    conn = await aiosqlite.connect(path)
    await conn.enable_load_extension(True)
    # load_extension 只有同步版，用 aiosqlite 的 _execute 把同步调用丢进它的工作线程。
    # _execute 是私有 API，但它是唯一能让同步扩展加载发生在正确线程的办法
    # （aiosqlite 的工作线程持锁，sqlite3 扩展加载必须与查询同线程）。
    await conn._execute(conn._conn.load_extension, sqlite_vec.loadable_path())  # type: ignore[no-untyped-call]
    await conn.enable_load_extension(False)
    return conn


def create_vector_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """建一个加载好 sqlite-vec 的 async engine。

    与 ``app.db.engine`` 分开：那个是通用 SQLite 连接，这个专供向量查询，
    避免每个普通请求都拖着扩展的开销。
    """
    path = _sqlite_path(url)
    return create_async_engine(
        "sqlite+aiosqlite://",
        async_creator=lambda: _open_with_extension(path),
        echo=echo,
        connect_args={"check_same_thread": False},
    )


def get_vector_engine() -> AsyncEngine:
    """进程内单例向量 engine。与 app.db.engine 同样策略。"""
    global _vector_engine
    if _vector_engine is None:
        _vector_engine = create_vector_engine(get_settings().database_url)
    return _vector_engine


_vector_engine: AsyncEngine | None = None


async def dispose_vector_engine() -> None:
    """测试 teardown 用。"""
    global _vector_engine
    if _vector_engine is not None:
        await _vector_engine.dispose()
        _vector_engine = None


# ── 建表 ────────────────────────────────────────────────────
async def ensure_vector_table(engine: AsyncEngine) -> None:
    """建 vec0 虚拟表（不存在才建）。

    vec0 是 SQLite 虚拟表，Alembic 不认它——autogenerate 看不到、也不该管。
    所以建表放在运行时兜底，而不是写进迁移。普通表仍走 Alembic。
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {VEC_TABLE} USING vec0("
                f"  chunk_id INTEGER PRIMARY KEY,"
                f"  embedding float[{EMBEDDING_DIM}]"
                f")"
            )
        )


# ── 写入 ────────────────────────────────────────────────────
async def upsert_embeddings(
    engine: AsyncEngine,
    pairs: Sequence[tuple[int, Sequence[float]]],
) -> int:
    """写入 (chunk_id, vector)。已存在的 chunk_id 会被替换。

    vec0 的主键列就是 chunk_id，所以「upsert」= DELETE + INSERT。
    重跑摄取同一份文档时靠这个覆盖旧向量。
    """
    if not pairs:
        return 0

    async with engine.begin() as conn:
        ids = ",".join(str(cid) for cid, _ in pairs)
        await conn.execute(text(f"DELETE FROM {VEC_TABLE} WHERE chunk_id IN ({ids})"))
        # AsyncConnection 没有 executemany——批量插入要 run_sync 到同步连接上做。
        def _insert(sync_conn: Connection) -> None:
            sync_conn.execute(
                text(f"INSERT INTO {VEC_TABLE} (chunk_id, embedding) VALUES (:cid, :vec)"),
                [{"cid": cid, "vec": json.dumps(list(vec))} for cid, vec in pairs],
            )

        await conn.run_sync(_insert)
    return len(pairs)


# ── 检索 ────────────────────────────────────────────────────
async def knn_search(
    engine: AsyncEngine,
    query: Sequence[float],
    limit: int,
    source_ids: Sequence[int] | None = None,
) -> list[tuple[int, float]]:
    """KNN 检索，返回 [(chunk_id, distance)]，**distance 越小越近**。

    ## distance 是 L2 欧氏距离，不是余弦距离

    实测（sqlite-vec 0.1.9，单位向量，真实 cos=0.5304）：
    ``distance=0.9692``，而 ``1-cos=0.4696``、``sqrt(2-2cos)=0.9692``——与 L2 逐位吻合。

    排序不受影响：所有向量都是单位向量时
    ``L2 = sqrt(2 - 2cos)``，是 cos 的单调递减变换，所以两种度量给出**同一个排序**。

    但阈值不能跨度量套用——「distance < 0.5」在 L2 下的含义
    与在余弦距离下完全不同。换 pgvector 时记得同步改这里的注释与调用方阈值。

    ## 另一个坑：嵌入不是确定性的

    同一段文本两次调嵌入服务，向量会有 ~1e-3 量级的浮点差异（累加顺序不同）。
    实测中三个切片两两余弦接近时（0.4679 vs 0.4485），这一点噪声足以让 top1
    和 top2 互换。所以**不要断言排名的绝对值**，只断言「正确答案在前列」。
    真实场景靠 top-k 取多条（我们要 top50 召回再 rerank），单条抖动不影响结果。

    ``source_ids`` 给定时只在这个文档集合里搜——用户私有资料必须先按
    source_id 收窄，否则会检索到别人的文档。
    """
    if len(query) != EMBEDDING_DIM:
        raise ValueError(f"查询向量维度应为 {EMBEDDING_DIM}，收到 {len(query)}")

    params: dict[str, object] = {
        "vec": json.dumps(list(query)),
        "k": limit,
    }
    # vec0 的 KNN 只认 MATCH + k/LIMIT。join 到普通表做 source 过滤。
    sql = (
        f"SELECT v.chunk_id AS chunk_id, v.distance AS distance "
        f"FROM {VEC_TABLE} v "
        f"WHERE v.embedding MATCH :vec AND k = :k "
    )
    if source_ids is not None:
        if not source_ids:
            return []
        sql += f"AND v.chunk_id IN (SELECT id FROM {CHUNK_TABLE} WHERE source_id IN ({_ids(source_ids)})) "
    sql += "ORDER BY v.distance"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return [(row[0], float(row[1])) for row in result]


def _ids(values: Sequence[int]) -> str:
    """把 id 序列拼成 SQL 列表片段（全是 int，无注入面）。"""
    return ",".join(str(v) for v in values)
