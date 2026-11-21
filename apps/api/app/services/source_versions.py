"""上传时的资料归组与落库。

gateway 只做 HTTP 解析；「这份资料属于哪一组」这套判定收在这里，
路由层不堆业务。

## 为什么上传时就要解析正文

归组靠正文相似度（TF-IDF 余弦），所以上传时得先拿到正文的头几片。
解析是同步的 CPU 密集调用（PDF 抽文本、DOCX 展开 XML），必须挪到线程池——
理由与 :func:`app.services.ingest.ingest` 里的 ``_parse`` 一样：它跑在
API 进程的事件循环里，一次卡住就是**整个进程的所有 HTTP 请求停摆**。

## 为什么解析失败不拦上传

归组是加分项：分错组的代价是多一份可检索的重复资料，
分不成的代价只是这份资料没跟旧版归到一起。

而「文件坏了」（加密 PDF、扫描件）本来就该由**摄取阶段**报一次错——
上传阶段先拦一道，用户眼前会出现两个不同的错误信息，且都不指向真正
要修的地方。所以这里解析失败就当空文本，让归组退化成自建新组。

## 为什么查重在存盘之前

重复上传不该在磁盘上留下没人引用的文件。所以顺序是
「算 hash → 查重 → 存盘 → 解析 → 归组 → 建行」。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceGroup, SourceStatus
from app.services import grouping, storage
from app.services.chunker import Chunk, TextChunker
from app.services.grouping import GroupingDecision
from app.services.ingest import parser_for
from app.services.parser import ParsedBlock

logger = logging.getLogger(__name__)


class DuplicateSourceError(Exception):
    """同一用户下已存在内容完全相同的资料。

    **只查 content_hash 相同**，不查相似度——近似但不同的文件应该被归为
    新版本，而不是被拒。

    message 是写给用户看的文案。
    """

    def __init__(self, message: str = "这份资料已经上传过了") -> None:
        super().__init__(message)


async def create_source_from_upload(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    source_type: str,
    filename: str,
    payload: bytes,
) -> Source:
    """上传一份文件：查重 → 存盘 → 归组 → 建行。返回新建的 Source 行。

    ## 抛什么

    - :class:`DuplicateSourceError` —— 内容完全相同，调用方转 409
    - :class:`app.services.storage.UploadTooLarge` —— 超大文件，调用方转 413

    ## 为什么建行放在最后

    归组判定要读库（比历史资料的画像），存盘要写文件系统。
    只有两者都成了才值得往库里插一行——插了行再发现要拒绝，就得再删回去。
    """
    digest = grouping.content_hash(payload)
    duplicate = await grouping.find_duplicate_hash(db, user_id, digest)
    if duplicate is not None:
        raise DuplicateSourceError()

    # 同内容但**没建成索引**的旧行（误点两次上传、或进程重启留下的僵尸行）
    # → 作废，让这次上传接管。
    #
    # 不能在这里抛 409：那会把「进程重启丢掉后台摄取任务」后的恢复路径
    # 也堵死——重传被拒，用户只能手动删僵尸行，而 409 的文案
    # 「这份资料已经上传过了」只字未提要删。
    await grouping.supersede_stale_pending(db, user_id, digest)

    # 存盘放在解析之前：超大文件在 storage 里就被拒，不用先白解析一遍。
    stored = storage.save_upload(payload, filename)

    decision = await _decide_grouping(db, user_id, payload=payload, source_type=source_type)
    group_id = await _ensure_group(db, user_id, decision)

    source = Source(
        user_id=user_id,
        title=title,
        source_type=source_type,
        storage_path=stored,
        size_bytes=len(payload),
        status=SourceStatus.PENDING,
        content_hash=digest,
        group_id=group_id,
        version_no=decision.version_no,
        is_active=decision.is_active,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


class NotIndexableError(Exception):
    """这份资料还不能设为生效版。

    **只允许已建成索引的版本接管生效位**——生效版是检索候选集的一员，
    一份没有切片的资料占了这个位置，等于「整组都搜不到」：

    旧版（indexed，10 切片）是唯一能用的，被顶掉归档；
    新版（failed，0 切片）成为生效版，但它一条切片都没有。

    用户看到的是「资料都还在，搜不到任何东西」，且没有任何错误提示。
    嵌入服务欠费（已知状态）会让摄取失败的版本很常见，这条检查拦的就是
    那个场景。
    """

    def __init__(self, message: str = "这份资料还没有建成索引，不能设为生效版") -> None:
        super().__init__(message)


async def activate(db: AsyncSession, source: Source) -> None:
    """把某份资料设为其所在组的**生效版本**，同组其他版本转归档。

    事务边界由调用方定：这里不 commit——调用方在自己的事务里提交，
    避免「旧版已归档、新版还没生效」被别的连接看到。

    抛 :class:`NotIndexableError`（资料还没建成索引）——调用方转 409。
    """
    if source.status != SourceStatus.INDEXED:
        raise NotIndexableError()
    await grouping.activate_version(db, source)


async def promote_after_delete(db: AsyncSession, source: Source) -> None:
    """删掉生效版后让组内剩下的版本接管（见 :func:`grouping.promote_after_delete`）。

    事务边界由调用方定。
    """
    await grouping.promote_after_delete(db, source)


# ── 内部 ───────────────────────────────────────────────────
async def _decide_grouping(
    db: AsyncSession,
    user_id: int,
    *,
    payload: bytes,
    source_type: str,
) -> GroupingDecision:
    """算出这份资料归到哪一组。"""
    # **先判池子，再解析**。
    #
    # 池子不足 ``MIN_CANDIDATES_FOR_GROUPING`` 份时归组一定不成立——
    # 那时再解析整篇就是纯浪费：一份 50MB 的 DOCX 展开 XML 要好几秒，
    # 用户的 201 响应被拖住，而结果被丢掉。
    #
    # 顺序反过来还有个副作用：解析失败会走「归组退化为自建新组」，
    # 白白打一条 warning 日志。
    if await grouping.candidate_pool_size(db, user_id) < grouping.MIN_CANDIDATES_FOR_GROUPING:
        return GroupingDecision(group_id=None, version_no=1, is_active=True)

    profile_text = await _profile_text(payload, source_type)
    return await grouping.resolve_grouping(db, user_id, profile_text=profile_text)


async def _ensure_group(db: AsyncSession, user_id: int, decision: GroupingDecision) -> int:
    """返回 group_id。判定说「自建新组」时就真的建一个。

    ``group_id`` 指向 ``source_groups.id``，而 source 的 id 要插完才有——
    所以组的 id 必须由这张表自己分配（理由见 ``models/source.py`` 里
    SourceGroup 的说明）。
    """
    if decision.group_id is not None:
        return decision.group_id
    group = SourceGroup(user_id=user_id)
    db.add(group)
    await db.flush()
    return group.id


async def _profile_text(payload: bytes, source_type: str) -> str:
    """取正文前几片拼成「画像文本」，供相似度比较。

    只取前 ``PROFILE_CHUNKS`` 片——理由见 ``grouping`` 的模块说明：
    简历的抬头信息才是「同一个人」最稳定的信号。

    ## 为什么画像要**切片**而不是直接取解析块

    候选资料的画像是「前 8 个**切片**」（``grouping.load_profiles`` 读
    ``document_chunks``，每片 ≤512 字符，约 4000 字符）。新建档这一侧
    若直接取「前 8 个**解析块**」，两边量级差一个数量级：

    - PDF：一块 = 一**页**（可能几千字）
    - HTML：一块 = **整页正文**（可能十万字）
    - TXT：一块 = **整段**（整篇文件）

    实测（同一份简历，项目描述很长）：新建档侧取 8 页（约 16000 字）
    而候选侧只有 8 片（约 4000 字）时，同一人的相似度掉到 **0.21**
    ——远低于 0.6 阈值 → **不归组** → 两个版本都生效、都进检索池，
    正是这个特性要消除的「互相冲突的证据」。

    所以两侧必须走**同一条切片链路**：这里也过一遍 ``TextChunker``，
    取前 ``PROFILE_CHUNKS`` 片。

    解析失败返回空串：调用方（``resolve_grouping``）会自建新组，
    **上传照常成功**。
    """
    try:
        blocks = await asyncio.to_thread(_parse_blocks, payload, source_type)
        chunks = await asyncio.to_thread(_chunk_blocks, blocks)
    except Exception:
        # 故意兜住所有解析异常（含解析器自身的意外错误）：这里的失败
        # 不该让上传失败。CancelledError 继承自 BaseException，不在
        # 这个范围里——取消信号照常往外传。
        logger.warning("上传时解析正文失败，归组退化为自建新组", exc_info=True)
        return ""
    return "\n".join(chunk.text for chunk in chunks[: grouping.PROFILE_CHUNKS])


def _parse_blocks(payload: bytes, source_type: str) -> list[ParsedBlock]:
    """同步解析（调用方负责挪到线程池）。"""
    return parser_for(source_type).parse(payload)


def _chunk_blocks(blocks: list[ParsedBlock]) -> list[Chunk]:
    """同步切片（调用方负责挪到线程池）。

    用的是摄取管线**同一个** ``TextChunker``（默认参数）——这样新建档侧
    与候选侧的切片口径完全一致，相似度比的是同类文本。
    """
    return TextChunker().chunk_blocks(blocks)
