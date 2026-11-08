"""联网搜索结果 → 可引用的来源（Source + DocumentChunk）。

## 要解决什么

critic 节点校验的是「正文里的 ``[n]`` 是不是被它引用的原文支撑」。
而原文来自 ``document_chunks``——按 ``chunk_id`` 查表。

联网搜索的结果原先**不是** chunk：它只是一段喂给模型的文本。于是：

- 正文里的角标指向不了公开来源（角标只对用户上传的资料成立）
- critic 拿不到公开来源的原文，校验只能跳过——DAG 上写「跳过校验：
  报告没有任何引用角标」
- 用户点不开「这个数字是哪来的」

## 怎么解决

把每条搜索结果落成**真正的** ``Source`` + ``DocumentChunk``：

    sources            一条 = 一个网页结果（source_type="web"）
      └ document_chunks 一条 = 一个切片（正文 = Tavily 给的摘要）

于是公开来源与用户资料**共用同一套角标编号**（``ReferenceTable``），
正文里的 ``[3]`` 唯一、可点开、可被 critic 校验。

## 三条硬约束

### 1. 不建索引 —— 否则污染后续的本地检索

BM25 与向量索引都按 ``document_chunks.id`` 建。公开来源的切片一旦进
索引，本地检索会召回它们——而它们是网页摘要，不是用户上传的资料。
用户问「我的资料里说了什么」，结果混进网上搜来的片段。

所以这里**只写业务表**，不碰 ``chunk_embeddings`` 与 FTS 表。

### 2. 不进用户的资料列表 —— 也不进本地检索的 source_ids

``Source.list_owned`` 是资料列表与本地检索（``_user_source_ids``）的
共同入口。公开来源要从那里排除，否则它会出现在「我的资料」里，
也会被本地检索当作用户的资料。

排除靠 ``source_type != "web"``——**不改 schema**（``sources`` 表没有
「公开来源」标记列，加列要写 Alembic 迁移并单独审）。

代价：``GET /sources/{id}/chunks`` 仍能按 id 查到它（那个端点直查
``source_id``，不经过 ``list_owned``）——这正是我们要的：角标要能点开
看原文。

### 3. 落库失败不能打断研究

正文已经流给用户了。落公开来源是**增益**——失败时那些结果仍然作为
纯文本证据参与 Analyst 的核对，只是不产生角标。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.source import WEB_SOURCE_TYPE, DocumentChunk, Source
from app.services.citation import Reference, ReferenceTable
from app.services.urls import canonicalize_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolEvidence:
    """一条联网搜索的结果。

    与 ``Reference`` 分开：那个带 chunk_id / source_id / 角标编号，
    指向用户上传的资料；这个是**外部网页**的内容。

    ## 两个长度字段，各有用途

    ``excerpt`` 是**短的**（给 Analyst 核对用）：模型要判断的只是
    「这几条说的是不是同一件事、有没有互相矛盾」，那个判断只需要看到
    结论层面的内容。喂全文会让 prompt 膨胀。

    ``content`` 是**长的**（给落库与 critic 校验用）：critic 校验的是
    「正文里的结论能不能从原文得到」，拿 200 字的摘要去校验等于
    **用摘要证明摘要**——正是 ``faithfulness.py`` 那条注释想避免的事。

    早先只有一个字段承担两个职责，短的赢了 —— 于是落库的正文也只有
    200 字，critic 校验的其实一直是摘要（CR 实测，2026-11-08）。
    """

    title: str
    excerpt: str
    """短摘要，给 Analyst 核对用。"""
    url: str = ""
    content: str = ""
    """完整内容，给落库与 critic 校验用。空串表示没有（退回用 excerpt）。"""


# 单条公开来源的正文长度上限（Tavily 摘要）。
#
# 与 ``RESULT_CONTENT_CHARS`` 同量级：再长就只对模型是负担，对校验
# 没有额外价值——校验要判断的是「这句结论能不能从原文得到」。
WEB_CHUNK_CHARS = 800


async def register_web_sources(
    db: AsyncSession,
    user_id: int,
    table: ReferenceTable,
    evidence: Sequence[ToolEvidence],
    seen_urls: set[str] | None = None,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
) -> list[tuple[int, ToolEvidence, Reference]]:
    """把联网搜索结果落成可引用的来源，并分配角标编号。

    返回**成功登记**的 ``(编号, 条目, 引用)`` 三元组。

    返回编号而不只是条目，是因为渲染证据块时必须用**引用表里的实际编号**
    ——用原始 evidence 配一个起始号算出来的编号会与引用表错位
    （见 :func:`render_web_evidence` 的说明）。

    同时返回 ``Reference`` 是因为调用方要把它交给前端（``reference`` 事件
    帧）与落盘（``report_sources``）。

    ## 为什么可能用**另一个 session**

    研究流跑 30-60 秒，SQLite 的写锁是库级的。用主 session 落库
    （``flush`` 不 ``commit``）会把写锁持有整轮研究——期间别的研究、
    用户的资料上传全被阻塞（实测 2026-11-08：并发研究 5.3 秒后报
    ``database is locked``）。

    给了 ``session_maker`` 就另开一个短事务：写完立刻 ``commit``，
    锁立刻释放。没有它时（单测路径）才用主 session + SAVEPOINT。

    ## 为什么不建索引

    见模块 docstring 的「三条硬约束」第 1 条：进索引就会污染本地检索。

    ## 为什么失败只跳过、不抛

    见「三条硬约束」第 3 条。落库失败时那条结果仍然作为纯文本证据
    参与 Analyst 核对，只是不产生角标。
    """
    if not evidence:
        return []

    created: list[tuple[int, ToolEvidence, Reference]] = []
    # 下一个可用编号。从表的当前长度起算——用户资料已经占掉了前面那些。
    next_n = len(table.all) + 1
    # 本轮已登记过的 URL（归一化后）。调用方没给就只用本轮的。
    seen = seen_urls if seen_urls is not None else set()
    for item in evidence:
        # **用长的那份**——落库的正文要给 critic 校验用。
        # 没有长内容时（测试或异常形状）才退回短摘要。
        content = (item.content or item.excerpt)[:WEB_CHUNK_CHARS]
        if not content.strip():
            continue
        # **同一个 URL 不重复登记**。
        #
        # 归一化后再比——同一篇文章的分享链接（带 ?fr=… / utm…）与
        # 原文是同一个东西。不去重的话它占两个角标号，而模型会把它们
        # 当成「两个独立来源互相印证」。
        # **畸形 URL 不能让整批失败**。
        #
        # ``urlsplit`` 对含 NFKC 异常字符的 URL 抛 ValueError（全角斜杠
        # 等）。一条坏 URL 抛出去 → 整批搜索结果都不产生角标——连同批里
        # 完全正常的那几条也一起没了。
        #
        # 归一化失败就当它没有 URL（不参与去重），其余照常登记。
        try:
            canonical = canonicalize_url(item.url) if item.url else ""
        except ValueError:
            logger.warning("搜索结果的 URL 无法归一化，按无 URL 处理", exc_info=True)
            canonical = ""
        if canonical and canonical in seen:
            continue
        # **表满了就别写库**。
        #
        # 先写 source/chunk 行再 ``table.add()`` 的话，表满时那两行成了
        # 孤儿：有行、没编号、用户点不到，还进了概览的资料计数
        # （CR 实测，2026-11-08）。
        #
        # 这个检查必须在 ``seen.add()`` **之前**——否则没落库的 URL 也被
        # 记成「已登记」，下一轮遇到它会被跳过，而它根本没进引用表。
        if table.is_full():
            table.count_dropped()
            logger.info("引用表已满，公开来源不再登记")
            break
        if canonical:
            seen.add(canonical)
        # **编号由本函数按序分配**，不取 ``len(table.all) + 1``。
        #
        # 两条踩过的路：
        # - 编号在 ``table.add()`` **之后**算 → 同一批里每条都是同一个号
        #   （表还没变），5 条公开来源全是 ``[11]``
        # - 编号在 ``table.add()`` 之后算但用 ``len(table.all) + 1`` →
        #   表已增长 +1、created 也 +1，编号变成 1、3、5、7、9，中间空号
        n = next_n
        # **独立 session 落库，写完立刻 commit**。
        #
        # SQLite 的写锁是库级的，持有整轮研究（30-60 秒）会阻塞并发研究
        # 与用户的资料上传（实测 2026-11-08：并发研究 5.3 秒后报
        # ``database is locked``）。
        #
        # ## 为什么**必须**是独立 session，不能用主 session
        #
        # 主 session 在研究期间要开着（读原文、最后落盘报告）。若在它上面
        # 落公开来源：
        #
        # - 用 SAVEPOINT：pysqlite 下「RELEASE SAVEPOINT == COMMIT」，
        #   会**偷偷提交主 session 的事务**——主循环之后的事务边界就乱了
        #   （切到 Postgres 这条路立刻失效，SAVEPOINT 不等于 COMMIT）。
        # - 裸 flush 不 commit：写锁持有整轮研究，阻塞所有别的写入。
        #
        # 两条都错。独立 session + 立即 commit 才是对的：主 session 的
        # 事务完全不受影响，锁也立刻释放。
        #
        # ## 没有 session_maker 时怎么办
        #
        # 只在**测试**里会这样（单测没有工厂）。那种情况下用 SAVEPOINT
        # 兜底，并明确记一笔——生产路径永远有工厂。
        if session_maker is not None:
            async with session_maker() as own_db:
                reference = await _create_web_source(own_db, user_id, table, item, content, n=n)
                if reference is not None:
                    await own_db.commit()
        else:
            reference = await _register_in_current_session(db, user_id, table, item, content, n=n)
        if reference is None:
            continue
        created.append((reference.n, item, reference))
        next_n += 1

    if created:
        logger.info("登记了 %d 条公开来源为可引用来源", len(created))
    return created


async def _register_in_current_session(
    db: AsyncSession,
    user_id: int,
    table: ReferenceTable,
    item: ToolEvidence,
    content: str,
    *,
    n: int,
) -> Reference | None:
    """在**当前 session** 里落一条公开来源。

    ## 这是**测试兜底路径**，生产不走

    生产一定有 ``session_maker``（网关层注入），走独立 session——见
    :func:`register_web_sources` 里「为什么必须��独立 session」。

    单测没有工厂，才走这里。

    ## 为什么用 SAVEPOINT

    flush 失败后 session 进入「事务已回滚」状态，后续任何 ``db.add()`` /
    ``flush()`` 都抛 ``PendingRollbackError``——实测（2026-11-07，
    SQLite + 开启 FK）：第一次 flush 抛 IntegrityError，之后的 flush
    全部抛 PendingRollbackError。

    不隔离的话，一条公开来源落库失败会**连累整轮研究**——后面落盘报告
    （``persist_report``）用同一个 session，它一失败报告就没了。而公开
    来源只是增益。

    用 ``begin_nested()``（SAVEPOINT）而不是 ``rollback()``：后者回滚
    **整个**事务，把这一轮里已写入的其它内容一起丢掉。

    ## 这条路径的已知限制

    pysqlite 下「RELEASE SAVEPOINT == COMMIT」——它会提交主 session 的
    事务。测试里无所谓（没有别的要提交），生产不走这条路。
    """
    savepoint = await db.begin_nested()
    try:
        reference = await _create_web_source(db, user_id, table, item, content, n=n)
        await savepoint.commit()
        return reference
    except Exception:
        logger.warning("公开来源落库失败，该条不产生角标", exc_info=True)
        try:
            await savepoint.rollback()
        except Exception:
            logger.warning("公开来源落库失败后回滚 savepoint 也失败", exc_info=True)
            # savepoint 回滚失败意味着外层事务也可能坏了——
            # 整体回滚，把 session 恢复到可用状态。
            try:
                await db.rollback()
            except Exception:
                logger.warning("公开来源落库失败后整体回滚也失败", exc_info=True)
        return None


async def _create_web_source(
    db: AsyncSession,
    user_id: int,
    table: ReferenceTable,
    item: ToolEvidence,
    content: str,
    *,
    n: int,
) -> Reference | None:
    """建一条公开来源 + 它的切片，并分配角标编号。

    表满时返回 None——那一条不产生角标（与本地检索的「引用表满了就
    丢弃」同语义）。
    """
    source = Source(
        user_id=user_id,
        title=item.title[:500],
        source_type=WEB_SOURCE_TYPE,
        status="indexed",
        url=item.url or None,
        # 公开来源没有原始文件——``storage_path`` 留空。
        chunk_count=1,
        char_count=len(content),
    )
    db.add(source)
    await db.flush()

    chunk = DocumentChunk(
        source_id=source.id,
        chunk_index=0,
        content=content,
        # 网页摘要没有页码。
        page=None,
    )
    db.add(chunk)
    await db.flush()

    reference = Reference(
        n=n,
        chunk_id=chunk.id,
        source_id=source.id,
        chunk_index=0,
        page=None,
        # **标题带「（公开来源）」标记**。
        #
        # Analyst 靠它分清「用户上传的资料」与「网上搜到的网页摘要」——
        # 跨来源的口径差异是最值得报告的矛盾，模型得能看出来。
        #
        # 之前 Analyst 用「编号的符号」区分两类（负数 = 公开来源），
        # 但那套编号从未实现：公开来源落成可引用来源后占的是正经角标号
        # （恒正数）。靠符号的约定是笔误，改成标题标记。
        title=f"{source.title}（公开来源）",
        excerpt=content[:120],
        # 公开来源不是「召回」来的——它是被搜到的。用 "网页搜索" 标注，
        # 前端角标 tooltip 才不会显示成「向量+BM25」。
        recall="网页搜索",
    )
    if not table.add(reference):
        # 表满了——这条不占号（``add`` 已记进 ``dropped``）。
        return None
    return reference


def render_web_evidence(entries: Sequence[tuple[int, ToolEvidence, Reference]]) -> str:
    """把**已登记的**公开来源渲染成带角标编号的证据块。

    ``entries`` 是 ``(编号, 条目)`` 对——编号必须与引用表里的**实际编号**
    一一对应。

    ## 为什么不能渲染全量 search 结果

    早先的写法是「渲染全部搜索结果，编号从 ``references[0].n`` 起算」。
    两者对不上：登记时会有条目被跳过（URL 去重命中、摘要全空白、引用表
    满了），而渲染不跳过——于是提示词里的 ``[n]`` 整体错位。

    实测（跨轮、同一 URL 带不同 utm）：
    ```
    实际引用表: [(1,'本地资料'), (2,'A'), (3,'B')]
    喂给模型的证据块:
    [3] A again      <- 引用表里 3 号是 'B'
    [4] B            <- 4 号不存在
    ```
    模型写 ``[3]`` → 前端点开是 B 的原文，提示词说的却是 A——**角标指错**，
    与这次改动要消灭的 bug 一模一样。

    所以渲染必须基于「实际登记成功的那几条」，编号直接用引用表里的值。

    ## 为什么要改编号本身

    原先 Tavily 的结果用它自己的 ``[1] [2]`` 序号，与角标编号是**两套
    编号**。模型在正文里写 ``[3]`` 时可能指的是 Tavily 的第 3 条，而
    引用表里的 3 号是用户资料的某个切片——角标指错，而且没有任何报错。

    共用一个编号空间之后，正文里的每个 ``[n]`` 唯一。
    """
    if not entries:
        return ""
    blocks = []
    for n, item, _reference in entries:
        # **用长的那份**——落库的正文要给 critic 校验用。
        # 没有长内容时（测试或异常形状）才退回短摘要。
        content = (item.content or item.excerpt)[:WEB_CHUNK_CHARS]
        # **URL 必须给模型看**。
        #
        # SYSTEM_PROMPT 明确要求「检索到的链接用 dedup 清理，避免把同一篇
        # 文章当成多份独立证据」——而 dedup 工具的入参是 URL 数组。模型
        # 在 tool_result 里看不到链接，就**没法执行这条指令**，也没法在
        # 正文里写出出处链接。
        #
        # 早先的改造把 URL 丢了（只渲染标题 + 摘要），那是遗漏不是取舍。
        url_line = f"URL: {item.url}\n" if item.url else ""
        blocks.append(f"[{n}] {item.title}\n{url_line}{content}")
    return "\n\n".join(blocks)


def web_citation_rules(start_n: int, upper: int) -> str:
    """写进 tool_result 的编号规则（联网来源部分）。

    ``start_n`` 是这批公开来源的第一个编号——它**不是 1**：用户资料
    已经占掉了前面那些号。规则里必须写实际的区间，否则模型会去引用
    不存在的号（1 号可能是用户资料的切片）。

    与 ``citation.citation_rules`` 的措辞分开——两者的证据来源不同，
    混成一句会让模型以为编号覆盖的是同一批东西。
    """
    if upper < start_n or start_n <= 0:
        return ""
    return (
        f"以上是联网搜索的结果，编号 [{start_n}] 到 [{upper}]。\n"
        f"写作规则：\n"
        f"- 基于这些结果的陈述，必须在句末标上对应编号（如 [{start_n}]）。\n"
        f"- 只能引用 [{start_n}]~[{upper}]，**严禁编造不存在的编号**。\n"
        f"- 不同来源说法冲突时，两边都标出来并说明分歧，不要只取其一。"
    )


__all__ = [
    "WEB_SOURCE_TYPE",
    "register_web_sources",
    "render_web_evidence",
    "web_citation_rules",
]
