"""BM25 全文检索（jieba 分词 + SQLite FTS5）。

## 为什么必须预分词

SQLite FTS5 自带的分词器对中文全都不可用：

- ``unicode61``（默认）—— 按 Unicode 规则切，中文整句当**一个词**，
  查「营业收入」匹配不到「本季度营业收入 32 亿美元」
- ``trigram`` —— 切 3 字符滑窗，**所有 2 字中文词全部查不到**。
  实测「能效」「营收」「算力」「功耗」命中数都是 0，而这恰好是中文技术词汇
  的主体

所以入库前用 jieba 切成词、词间空格连接，查询时同样切分。FTS5 拿到的是
已经被词化的文本，用 ``unicode61`` 按空格切就正好。

## AND 还是 OR

FTS5 的 ``MATCH`` 默认是 AND：「营业收入」被 jieba 切成「营业 收入」，
两个词必须同时出现。而 BM25 的价值在于按词频打分，不在���做交集过滤——
「营收」这个词漏了，AND 就把整篇文档排除了，混合检索的语义召回也废了。

所以查询串用 ``OR`` 连接所有词，让 BM25 靠打分排序（更常见的词得分更高），
召回交给向量那一路去补。

## 与向量检索的关系

本模块只管「关键词匹配」这一路。合并由 :mod:`app.services.retriever`
用 RRF 做——两路的分数尺度完全不同（L2 距离 vs BM25 负分），
不能直接加权平均。

## 已知的召回缺口

jieba 把「营业收入」切成「营业 收入」，查「营收」时交集为空，一条都命中不了。
这是分词的固有性质，不是 bug：**文档里压根没有「营收」这两个字**。
2 字滑窗也救不了（原文的滑窗是「业收」不是「营收」）。

这类同义/变体的漏召回交给向量那一路兜——嵌入模型知道「营收」和
「营业收入」讲的是同一件事。BM25 的强项是专有名词（`H100`、`B200`），
不是语义。所以**混合检索不是可选项**：只做向量会漏专有名词，只做 BM25 会漏同义词。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import jieba
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# jieba 默认往 stderr 打词典加载日志，在后台任务里会污染错误输出
jieba.setLogLevel(logging.WARNING)

FTS_TABLE = "chunk_fts"
FTS_COLUMN = "tokenized"


@dataclass(frozen=True, slots=True)
class Bm25Hit:
    """一条 BM25 命中。``score`` 越小越相关（bm25() 的原始语义）。"""

    chunk_id: int
    score: float


def tokenize(text_content: str) -> str:
    """jieba 分词，用空格连接。

    丢掉不含字母数字的 token——纯标点（``，。%``）在 FTS5 里是分隔符，
    留着只会让 MATCH 表达式变脏。
    """
    return " ".join(tok for tok in jieba.cut(text_content) if _is_meaningful(tok))


def _is_meaningful(token: str) -> bool:
    """token 里至少要有一个字母或数字。"""
    return any(ch.isalnum() for ch in token)


async def ensure_fts_table(engine: AsyncEngine) -> None:
    """建 FTS5 虚表（不存在才建）。

    与 vec0 同理：Alembic 不认虚表，所以归运行时兜底而不是迁移。

    不要用 contentless FTS5（``content=''``）：它省存储但**不支持 DELETE**，
    而重跑摄取必须能删掉旧条目。实测报
    ``cannot DELETE from contentless fts5 table``。
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} "
                f"USING fts5({FTS_COLUMN}, tokenize='unicode61') "
            )
        )


async def index_chunks(engine: AsyncEngine, pairs: Sequence[tuple[int, str]]) -> None:
    """写入 (chunk_id, 原文)。入库时自动分词。

    自己先 ensure 表：DELETE 目标不存在时 SQLAlchemy 会把「no such table」
    当成 ProgrammingError 抛出来，而不是让 CREATE 兜住。
    """
    if not pairs:
        return
    await ensure_fts_table(engine)
    ids = ",".join(str(cid) for cid, _ in pairs)
    async with engine.begin() as conn:
        await conn.execute(text(f"DELETE FROM {FTS_TABLE} WHERE rowid IN ({ids})"))
        await conn.execute(
            text(f"INSERT INTO {FTS_TABLE} (rowid, {FTS_COLUMN}) VALUES (:id, :tok)"),
            [{"id": cid, "tok": tokenize(content)} for cid, content in pairs],
        )


async def search(
    engine: AsyncEngine,
    query: str,
    limit: int,
    source_ids: Sequence[int] | None = None,
) -> list[Bm25Hit]:
    """BM25 检索，返回按相关度从高到低（score 升序）。

    ``source_ids`` 与向量检索同义——用户私域隔离，两者都必须收窄。

    表不存在时返回空而不是报错：一份资料都没摄取过的部署就该检索到 0 条。
    """
    await ensure_fts_table(engine)
    tokens = [t for t in tokenize(query).split() if t]
    if not tokens:
        return []

    # 双引号包词，避免 jieba 切出的词里混入 FTS5 的语法符号
    match_expr = " OR ".join(f'"{t}"' for t in tokens)
    sql = (
        f"SELECT rowid AS chunk_id, bm25({FTS_TABLE}) AS score "
        f"FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH :q "
    )
    params: dict[str, object] = {"q": match_expr, "n": limit}
    if source_ids is not None:
        if not source_ids:
            return []
        ids = ",".join(str(s) for s in source_ids)
        sql += f"AND rowid IN (SELECT id FROM document_chunks WHERE source_id IN ({ids})) "
    sql += "ORDER BY score LIMIT :n"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return [Bm25Hit(chunk_id=row[0], score=float(row[1])) for row in result]
