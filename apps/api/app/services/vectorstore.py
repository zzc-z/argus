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
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config import get_settings

# ── 常量 ────────────────────────────────────────────────────
# embedding 维度必须与写入时的模型一致，改了要重建 vec0 表（维度写在建表 DDL 里）。
# 1536 = OpenAI text-embedding-3-small 的原始维度。不降维：512 维版本是
# PRD 早期估算，1536 检索质量更好，且 sqlite-vec 的 float[N] 存的是 float32。
EMBEDDING_DIM = 1536

# 向量 engine 的连接数。给 4 是配合 gateway/research.py 的
# MAX_CONCURRENT_STREAMS：并发研究请求各自占一个连接，摄取任务再要几个。
# 不能配 1——那会让并发摄取直接死锁（见 create_vector_engine 的说明）。
VECTOR_POOL_SIZE = 4

VEC_TABLE = "chunk_embeddings"
CHUNK_TABLE = "document_chunks"

# vec0 虚拟表的**影子表**：主键索引表，一行一个向量。
#
# 用途只有一个——在没有 sqlite-vec 扩展的连接上数向量个数。直接查
# ``chunk_embeddings`` 要扩展，查这张影子表不用（它是真实表）。
# 行数与向量数一致：vec0 的主键就是 chunk_id。
VEC_ROWIDS_TABLE = "chunk_embeddings_rowids"


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

    ## 必须显式指定池类型，否则是死锁不是慢

    传了 ``async_creator`` 之后，SQLAlchemy 对 SQLite 方言的默认选择是
    :class:`StaticPool`——**全进程共用同一条连接**。实测（本函数创建出来的
    engine）：``StaticPool``；而 ``app.db.engine`` 是 ``AsyncAdaptedQueuePool``。

    单连接的 checkout 不排他，于是两个并发 ``engine.begin()`` 落在同一个
    SQLite 事务里：一个提交、另一个回滚，谁先提交谁被吞。更糟的是两个
    事务各自持有同一把连接又互相等对方释放，直接死锁——实测 8 个并发
    ``upsert_embeddings`` 的脚本是**挂住**的，不是报错退出。

    生产触发路径很普通：用户同时上传两份资料 → ``_schedule_ingest`` 起两个
    摄取任务 → 两者都调 ``upsert_embeddings``，内部是 DELETE + INSERT 两个
    await 点。而测试抓不到，因为 ``shared_db`` fixture 让 ORM session 与向量
    engine 共用同一个 engine，连接数恒为 1，且用例全部串行 await。

    所以这里显式给 ``AsyncAdaptedQueuePool``，让每个并发调用方拿到自己的
    连接。SQLite 本身靠文件锁保证写串行，那正是我们要的——要串行的是
    **写入**，不是「让所有人挤一条连接」。
    """
    path = _sqlite_path(url)
    return create_async_engine(
        "sqlite+aiosqlite://",
        async_creator=lambda: _open_with_extension(path),
        echo=echo,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=VECTOR_POOL_SIZE,
        max_overflow=0,
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


# ── 统计 ────────────────────────────────────────────────────
async def count_embeddings(db: AsyncSession) -> int:
    """数向量表里有几行。

    ## 为什么查影子表而不是 ``chunk_embeddings`` 本身

    ``chunk_embeddings`` 是 vec0 虚拟表，直接查它要加载 sqlite-vec 扩展
    ——普通 SQLAlchemy session 查会报 ``no such module: vec0``，而向量
    engine 与业务 engine 是两个不同的连接池（见 ``create_vector_engine``）。

    vec0 会为每张虚表建一组**影子表**（``chunk_embeddings_rowids`` 等），
    它们是真实表，普通 SQL 就能查。``chunk_embeddings_rowids`` 是主键
    索引表，一行一个向量，行数就是向量数（实测与虚表 count 一致）。

    走影子表的好处不只是省一个连接池：它让这个统计能在**业务 session**
    里做，于是测试覆盖 ``get_session`` 就够了，不必再覆盖向量 engine
    ——后者在 conftest 里返回的是同步 engine，类型与生产代码的
    ``AsyncEngine`` 不符（那次不一致潜伏了很久，因为路由测试都用了
    假 agent，向量 engine 从没被真的用过）。

    表不存在时返回 0：还没建过向量库是正常状态（一份资料都没摄取过），
    不该让整个状态接口 500。
    """
    exists = await db.scalar(
        text("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": VEC_ROWIDS_TABLE},
    )
    if not exists:
        return 0
    count = await db.scalar(text(f"SELECT count(*) FROM {VEC_ROWIDS_TABLE}"))
    return int(count or 0)


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
    source_ids: Sequence[int],
) -> list[tuple[int, float]]:
    """KNN 检索，返回 [(chunk_id, distance)]，**distance 越小越近**。

    表不存在时返回空而不是报错：一份资料都没摄取过的部署就该检索到 0 条。

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

    ## ``source_ids`` 是必填，不是可选

    用户私有资料必须先按 source_id 收窄，否则会检索到别人的文档。
    这里**故意不给默认值**：默认 ``None`` 等于「不传就搜全库」，而漏传
    恰恰是最容易犯的错误——它不会报错，只会让 A 用户的资料出现在 B 用户的
    研报里。必填参数把「忘了收窄」从静默事故变成 TypeError。

    传空列表时返回空：该用户一份资料都没有。
    """
    if len(query) != EMBEDDING_DIM:
        raise ValueError(f"查询向量维度应为 {EMBEDDING_DIM}，收到 {len(query)}")
    await ensure_vector_table(engine)

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
