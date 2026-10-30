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

# 相关性下限：距离超过它的切片当「不相关」，不返回。
#
# 没有下限的后果实测过：用户问「iPhone 折叠屏 对比 国产折叠屏质量」，
# 资料库里只有一份医保接口文档，检索照样召回 12 条「参保人手机 | tel」，
# 模型拿它当证据去回答手机质量对比。
MAX_RELEVANT_DISTANCE = 0.45
"""相关性下限（**绝对**）：**余弦距离**大于它就不返回。

## 为什么用余弦距离而不是 L2

L2 对**模长**敏感：方向相同、模长差 20 倍的两个向量，L2 能差出十几个
单位，直接越过任何阈值。实测 dev 库里就混着 9 个模长 19.596 的脏向量
（早期测试留下的 ``[0.5] * 1536``），其余 7389 个是 1.0——用 L2 判相关性
就等于让「这个切片的模长恰好多大」决定它相不相关。

余弦距离只看**方向**，对模长免疫：实测同一向量放大 2 倍，余弦距离仍是
0.0（完全同向），反向则是 2.0（完全反向）。所以用它判相关性不需要
「存量向量都是单位向量」这个前提，也不需要在入库时归一化。

## 与 ``knn_search`` 返回值的关系

``knn_search`` 返回的**仍然是 L2**（项目既有契约，见
``test_distance_is_l2_not_cosine``——换 pgvector 时那个契约会变）。
余弦距离只在**过滤时**用：两条度量都在同一次 KNN 查询里取出来
（sqlite-vec 的 KNN 支持同时 select ``v.distance`` 与
``vec_distance_cosine(v.embedding, :vec)``），所以过滤与排序仍由 L2 主导，
不改变返回值的语义。

## 标定依据（生产库同一份资料实测，2026-10-26，7 组相关 + 7 组不相关查询）

**相关**查询的 top-20 距离全部 ≤ **0.4006**；
**不相关**查询的 top-20 距离全部 ≥ **0.6234**。

0.45 取在两者之间，且离两端都有余量：

- 0.40 会被误杀：查询「个人医疗消费费用清单」时，4 条
  「本接口用于查询医保个人账户的交易明细信息。」距离 0.4006——
  那是「个人医疗消费」之外的**另一个实体**的证据，丢掉它答案就变单边。
- 0.65 会放进不相关内容：不相关查询在 0.65 阈值下平均残留 3.6 条。

**换嵌入模型要重新标定这个阈值**：嵌入模型换了之后「相关」与「不相关」
的相似度分布也会变。
"""

def is_relevant(cosine_distance: float) -> bool:
    """这条切片算不算「相关」——余弦距离不超过 :data:`MAX_RELEVANT_DISTANCE`。

    ## 为什么是单一绝对阈值（2026-10-26 实测后定）

    业界常见的做法是双层：``effective = max(绝对下限, top-1 距离 × ratio)``。
    本项目实测下来**相对层不起作用**，所以没有引入它：

    相对层只在 ``top-1 × ratio > 绝对下限`` 时才比绝对层严，即
    ``top-1 > 0.60``（ratio 0.75、绝对 0.45）。而实测数据里：

    - 相关查询的 top-1 全部 ≤ 0.2577 → 相对层永远不比绝对层严
    - 不相关查询的 top-1 全部 ≥ 0.6234 → 相对层收紧时，绝对层**已经**
      把它们挡住了（top-1 距离 0.6234 > 0.45）

    两层在这 7+7 组实测查询上**完全等价**。多一个没有实测依据的参数
    只会让下一个人以为它在做什么——按项目规则「注释里的技术断言要么实测过，
    要么不写」，不加。

    ## 「第二实体」的证据靠放宽绝对阈值保住，不靠相对层

    实测反例：查询「个人医疗消费费用清单」时，top-1 距离 0.1855，
    而「本接口用于查询医保个人账户的交易明细信息。」距离 0.4006——
    那是**另一个实体**的证据，切掉它答案就变单边。
    绝对阈值从 0.40 放宽到 **0.45** 就是为了留住它（0.45 ≤ 0.45）。

    相对层在这个形态下帮不上忙：``0.1855 × 0.75 = 0.139``，
    比绝对阈值宽裕，两层取更严的那个 = 绝对层。
    """
    return cosine_distance <= MAX_RELEVANT_DISTANCE


# ── 引擎构造 ────────────────────────────────────────────────
def _sqlite_path(url: str) -> str:
    """从 SQLAlchemy URL 里取出裸文件路径。

    ``sqlite+aiosqlite:///./argus.db`` → ``./argus.db``。
    async_creator 只能拿到文件路径，拿不到 ``sqlite+aiosqlite://`` 这种 URL。
    """
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"向量库扩展只支持 SQLite，当前 database_url 是 {url.split('://')[0]}")
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
async def count_embeddings(db: AsyncSession, user_id: int | None = None) -> int:
    """数向量表里有几行。

    ``user_id`` 给了就只数**该用户**的向量（join sources 过滤），不给就
    数全库。页面上「检索切片」与「已向量化」两个数字要同口径，所以那里
    传的是 user_id。

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
    if user_id is None:
        count = await db.scalar(text(f"SELECT count(*) FROM {VEC_ROWIDS_TABLE}"))
        return int(count or 0)
    # 按 user 过滤：影子表只有 chunk_id，没有 user_id 列，要 join 一条到
    # sources。不这么做的话「已向量化」数的是全库的，而旁边的「检索切片」
    # 数的是当前用户的——两个不同口径的数字并排显示，用户没法解读。
    count = await db.scalar(
        text(
            f"SELECT count(*) FROM {VEC_ROWIDS_TABLE} AS v "
            f"JOIN document_chunks AS c ON c.id = v.chunk_id "
            f"JOIN sources AS s ON s.id = c.source_id "
            f"WHERE s.user_id = :user_id"
        ),
        {"user_id": user_id},
    )
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

    但阈值不能跨度量套用——这里的返回值是 L2，而相关性判定用的是
    余弦距离（见 :data:`MAX_RELEVANT_DISTANCE`）。换 pgvector 时记得
    同步改这里的注释与调用方阈值。

    ## 相关性下限在这里生效

    超过 :data:`MAX_RELEVANT_DISTANCE` 的行**不返回**。放在这一层而不是
    调用方，是因为本模块是「向量库接入层」——语义上它就该只给出「够近的」。
    阈值从模块常量读（不是函数默认参数），改动常量即刻生效。

    ## 两个度量各司其职

    - **返回值**是 sqlite-vec 原样返回的 **L2**，没做任何缩放——
      这是对外的既有契约（换 pgvector 时要保持），不是相关性判定的依据。
    - **相关性判定**用 ``vec_distance_cosine``（余弦距离），与
      :data:`MAX_RELEVANT_DISTANCE` 标定时用的是同一个量。

    之所以不拿 L2 判相关性：L2 对**模长**敏感，方向相同、模长差 20 倍的
    两个向量，L2 能差出十几个单位，直接越过任何阈值。余弦只看方向，
    对模长免疫。

    :func:`chunk_distances` 用的是同一个余弦度量（同一个查询向量、
    同一个 ``vec_distance_cosine``）、同一个阈值，所以两条路对同一个
    切片的判断不会打架。

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
    #
    # 同时取两个度量：``v.distance`` 是 KNN 的原生 L2（对外返回值），
    # ``vec_distance_cosine`` 是余弦距离（相关性判定用）。sqlite-vec 的
    # KNN 支持在同一次查询里 select 两者，不额外扫一遍向量表。
    sql = (
        f"SELECT v.chunk_id AS chunk_id, v.distance AS distance, "
        f"vec_distance_cosine(v.embedding, :vec) AS cosine_distance "
        f"FROM {VEC_TABLE} v "
        f"WHERE v.embedding MATCH :vec AND k = :k "
    )
    if not source_ids:
        return []
    sql += (
        f"AND v.chunk_id IN (SELECT id FROM {CHUNK_TABLE} WHERE source_id IN ({_ids(source_ids)})) "
    )
    sql += "ORDER BY v.distance"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = [(row[0], float(row[1]), row[2]) for row in result]
    # 相关性下限按**余弦距离**判定（见 MAX_RELEVANT_DISTANCE）。
    # 返回的仍是 L2——那是对外的既有契约，不因过滤而改变。
    #
    # 余弦距离是 NULL 表示有一侧是零范数向量（方向不存在）——
    # sqlite-vec 对这种输入返回 NULL 而不是数。零范数向量没有方向，
    # 谈不上相关不相关，**当不相关处理**（挡掉），而不是让 float(None)
    # 抛 TypeError 把整条检索路挂掉。
    return [
        (cid, l2)
        for cid, l2, cos in rows
        if cos is not None and is_relevant(cos)
    ]


async def chunk_distances(
    engine: AsyncEngine,
    query: Sequence[float],
    chunk_ids: Sequence[int],
    source_ids: Sequence[int],
) -> dict[int, float]:
    """查指定 chunk_id 到查询向量的距离，返回 {chunk_id: distance}。

    用途：BM25 那一路只拿得到「哪些切片字面命中了」，拿不到距离。
    要让 BM25 路也过相关性下限，就得回头查这些 id 的向量距离。

    ## 为什么不用「带 id 约束的 KNN」

    试过：``WHERE embedding MATCH :vec AND k = :k AND chunk_id IN (...)``。
    sqlite-vec 的 ``k`` 是**全局**最近 k 行的条数，id 约束在其**之后**生效——
    请求的 id 不在全局最近 k 行里就查不到（实测：请求最远的那行，k=5 返回空、
    k=10 才返回）。而相关性下限要挡掉的恰恰是「离得远」的那些行 ⇒ 用 KNN
    查它们必然落空。

    改成直接算：``vec_distance_cosine`` 是 sqlite-vec 的标量函数（不依赖 KNN
    路径），配 ``chunk_id IN (...)`` 走主键索引，命中即精确距离。

    ## 距离的度量与向量路一致

    返回的是**余弦距离**（``1 - cos``），与 :func:`knn_search` 内部做相关性
    判定用的是同一个度量、同一套阈值（:func:`is_relevant`），所以两条路
    对同一个切片的判断不会打架。

    用余弦而不是 L2 的理由见 :data:`MAX_RELEVANT_DISTANCE` 的说明——
    简言之：L2 对模长敏感，余弦只看方向。

    ## 租户隔离：**在数据库里收窄**，不靠调用方自觉

    ``source_ids`` 是**必填**，且收窄发生在 SQL 里（子查询），不是
    「调用方先过滤一遍再传 id」。业界多租户向量检索的标准做法是
    **pre-filter in the database, never post-filter in application code**——
    应用层过滤一旦漏掉，跨租户泄漏**不会报错**，只会静默地把别人的资料
    送进研报。

    所以本函数**同时**要求 ``chunk_ids`` 与 ``source_ids``：前者说「查哪些
    切片」，后者说「这些切片属于谁」。两者都对上才查得到。

    没有向量的 id 不在返回的 dict 里（调用方按「查不到距离」处理）。
    空列表返回空 dict。
    """
    if len(query) != EMBEDDING_DIM:
        raise ValueError(f"查询向量维度应为 {EMBEDDING_DIM}，收到 {len(query)}")
    if not chunk_ids or not source_ids:
        return {}
    await ensure_vector_table(engine)

    params: dict[str, object] = {"vec": json.dumps(list(query))}
    # 租户收窄在 SQL 里做（JOIN），不靠调用方自觉——见 docstring 的「租户隔离」。
    #
    # 为什么用 JOIN 而不是第二个 ``IN (SELECT ...)``：sqlite-vec 限制一张 vec0
    # 表里只能有**一个** ``rowid in (..)`` 运算符（实测报
    # ``only 1 'rowid in (..)' operator is allowed in a single vec0 query``）。
    # JOIN 到普通表不算那个运算符。
    sql = (
        f"SELECT v.chunk_id AS chunk_id, "
        f"vec_distance_cosine(v.embedding, :vec) AS cosine_distance "
        f"FROM {VEC_TABLE} v "
        f"JOIN {CHUNK_TABLE} c ON c.id = v.chunk_id "
        f"WHERE v.chunk_id IN ({_ids(chunk_ids)}) "
        f"AND c.source_id IN ({_ids(source_ids)}) "
    )

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        # 零范数向量会让 ``vec_distance_cosine`` 返回 NULL（实测）——
        # 那种行**不返回**：调用方拿不到距离就不会拿它当证据，
        # 也省得 float(None) 把整条路炸掉。
        return {
            int(row[0]): float(row[1])
            for row in result
            if row[1] is not None
        }


def _ids(values: Sequence[int]) -> str:
    """把 id 序列拼成 SQL 列表片段（全是 int，无注入面）。"""
    return ",".join(str(v) for v in values)
