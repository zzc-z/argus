"""资料源路由：上传、建源、查状态。

## 摄取是异步的，不阻塞 HTTP 响应

摄取一份 50 页 PDF 要 30-60 秒（切片 → 嵌入 → 向量入库），其中嵌入是
网络往返。同步跑完再返回，用户会盯着转圈几十秒，且中途断线就白跑。

所以：端点**只建源**（毫秒级）然后立刻返回 201，前端拿 source_id 轮询
状态端点。这与 research 的 SSE 是两套机制——摄取不需要逐 token 反馈，
「正在切片 142/180」这种阶段进度轮询足够。

代价是进程重启会丢正在跑的摄取（status 停在中间态）。当前没有任务队列，
YAGNI：先这样，真需要时接 Redis + worker。

## URL 建源走同一条路

``POST /url`` 同样只建源、抓取放后台——抓一个站可能耗满 20 秒超时，
同步做等于让前端转圈 20 秒才拿到一个必然失败的 4xx。

抓取失败（超时 / 404 / 非公网地址）与摄取失败对用户是**同一种事**，
所以都写进 ``sources.error_message`` + ``status=failed``，
轮询端点不需要区分。URL 合法性也故意不在请求里校验：
放在后台让它落到 error_message，前端处理「建源失败」和「摄取失败」用同一套逻辑。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_session
from app.gateway.deps import CurrentUser
from app.models import DocumentChunk, Source, SourceStatus, SourceType
from app.models.report import ReportSource
from app.schemas.source import (
    ChunkResponse,
    SourceCreate,
    SourceListResponse,
    SourceResponse,
)
from app.services import storage
from app.services.fetcher import FetchError, fetch_for_ingest
from app.services.ingest import IngestError, ingest, mark_failed
from app.services.vectorstore import get_vector_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

# 扩展名 → 资料类型。映射不到就拒——猜类型会解析出乱码。
# 扩展名 → 资料类型。映射不到就拒——猜类型会解析出乱码。
#
# **`.doc` 不在表里**：那是 Word 97-2003 的二进制格式（Compound File
# Binary），与 .docx 的 OOXML 是两种东西，python-docx 读不了。给它硬塞
# 一个 parser 的结果是解析出乱码且不报错。要支持得另找方案，不在这里
# 半吊子兜住。
_EXT_TO_TYPE: dict[str, SourceType] = {
    ".pdf": SourceType.PDF,
    ".html": SourceType.HTML,
    ".htm": SourceType.HTML,
    ".txt": SourceType.TEXT,
    ".md": SourceType.TEXT,
    ".markdown": SourceType.TEXT,
    ".docx": SourceType.DOCX,
}


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def upload_source(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="PDF / DOCX / HTML / TXT / Markdown")],
) -> SourceResponse:
    """上传文件建源。立刻返回，摄取在后台跑。

    202而不是 201？不——201 准确，资源已创建且有 id。区别只在语义。
    """
    source_type = _EXT_TO_TYPE.get(_suffix(file.filename))
    if source_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "只支持 PDF / DOCX / HTML / TXT / Markdown 文件",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件内容为空")

    try:
        stored = storage.save_upload(payload, file.filename or "upload")
    except storage.UploadTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc

    source = Source(
        user_id=user.id,
        title=file.filename or "未命名资料",
        source_type=source_type,
        storage_path=stored,
        size_bytes=len(payload),
        status=SourceStatus.PENDING,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    _schedule_ingest(source.id, payload)
    return SourceResponse.model_validate(source)


@router.post("/url", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_from_url(
    payload: SourceCreate,
    user: CurrentUser,
    db: DbSession,
) -> SourceResponse:
    """用 URL 建源。立刻返回，抓取在后台跑。

    与 upload_source 同构：抓一个站可能要 20 秒（超时上限），不能占着 HTTP
    连接让前端转圈。URL 合法性也留给后台——让它落到 error_message 而不是
    HTTP 状态码，前端轮询时两种失败的处理动作是同一个。
    """
    source = Source(
        user_id=user.id,
        title=payload.title,
        source_type=payload.source_type,
        url=payload.url,
        status=SourceStatus.PENDING,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    _schedule_url_ingest(source.id, payload.url, payload.source_type)
    return SourceResponse.model_validate(source)


@router.get("", response_model=SourceListResponse, summary="列出我的资料")
async def list_sources(user: CurrentUser, db: DbSession) -> SourceListResponse:
    sources = await Source.list_owned(db, user.id)
    # 一条 group_by 算全部资料的被引次数，而不是每行发一条 SELECT。
    # 计数口径是「引用了几份报告」而非「被引用了几次」——sources 页那一列
    # 问的是「有几篇报告用过我」，不是「出现了几次」。
    cited = await _citation_counts(db, [s.id for s in sources])
    return SourceListResponse(
        items=[
            SourceResponse.model_validate(s).model_copy(
                update={"citation_count": cited.get(s.id, 0)}
            )
            for s in sources
        ],
        total=len(sources),
    )


@router.get("/{source_id}", response_model=SourceResponse, summary="查单个资料状态")
async def read_source(source_id: int, user: CurrentUser, db: DbSession) -> SourceResponse:
    """轮询端点。前端拿它显示「正在切片 142/180」。"""
    source = await _owned(db, source_id, user.id)
    # citation_count 在这里也要算：否则同一个字段在列表端点有值、详情
    # 端点恒为 0（落到 schema 默认值），前端轮询时会看到数字自己掉回 0。
    counts = await _citation_counts(db, [source.id])
    return SourceResponse.model_validate(source).model_copy(
        update={"citation_count": counts.get(source.id, 0)}
    )


@router.get("/{source_id}/chunks", response_model=list[ChunkResponse], summary="列出切片")
async def list_chunks(
    source_id: int,
    user: CurrentUser,
    db: DbSession,
) -> list[ChunkResponse]:
    """返回切片全文。仅限资料所有者。"""
    await _owned(db, source_id, user.id)
    chunks = await DocumentChunk.list_for_source(db, source_id)
    return [ChunkResponse.model_validate(c) for c in chunks]


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, user: CurrentUser, db: DbSession) -> None:
    """删除资料及其切片。

    原始文件与向量不在这里清——向量表没有外键，靠 DB 级联删不到。
    暂留给 W3 的清理任务；当前用量下孤儿向量不影响正确性（检索按
    chunk_id 回查，查不到就丢弃），但**这是个已知缺口，不是设计**。
    """
    await db.delete(await _owned(db, source_id, user.id))
    await db.commit()


# ── 内部 ───────────────────────────────────────────────────
async def _citation_counts(db: AsyncSession, source_ids: list[int]) -> dict[int, int]:
    """资料 id → 被多少份报告引用。

    **按报告去重**：同一份报告引用同一资料的 5 个切片，仍算 1 篇。直接
    ``count(*)`` 会把「被引得多的资料」显示成「被很多报告提到」。

    去重放在 SQL 侧（``count(distinct report_id)`` + ``group_by``），返回
    行数与**报告数**同阶；拉全部引用行进 Python 去重会让返回行数与
    「报告数 × 每篇切片数」同阶——单用户数据量下就能差出几十倍，而
    ``read_source`` 是摄取进度轮询端点，会每秒跑两遍。

    结果只包含被引用过的资料；未出现在字典里的就是 0。
    """
    if not source_ids:
        return {}
    rows = (
        await db.execute(
            select(
                DocumentChunk.source_id,
                func.count(distinct(ReportSource.report_id)),
            )
            .join(DocumentChunk, DocumentChunk.id == ReportSource.chunk_id)
            .where(DocumentChunk.source_id.in_(source_ids))
            .group_by(DocumentChunk.source_id)
        )
    ).all()
    return dict(rows)


async def _owned(db: AsyncSession, source_id: int, user_id: int) -> Source:
    """取资料并校验归属。找不到或不是本人的，一律 404。

    刻意不区分「不存在」和「不是你的」——报 403 等于确认了这个 id 存在，
    是信息泄露。
    """
    source = await Source.find_owned(db, source_id, user_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资料不存在")
    return source


def _schedule_ingest(source_id: int, payload: bytes) -> None:
    """把摄取丢到后台跑。

    刻意**不复用**请求的 db session——它随请求结束关闭。后台任务自己开
    一个 session，否则跑到一半 session 已关，错误还很难看出来。
    """
    _spawn(_ingest_with_payload(source_id, payload))


def _schedule_url_ingest(source_id: int, url: str, source_type: str) -> None:
    """URL 建源的后台入口：先抓，再走同一条摄取管线。

    刻意复用 :func:`_ingest_with_payload` 而不是另写一份摄取逻辑——
    「抓到的字节怎么入库」与「上传的字节怎么入库」没有任何区别，
    两条路各写一遍必然漂移。
    """
    _spawn(_fetch_then_ingest(source_id, url, source_type))


async def _fetch_then_ingest(source_id: int, url: str, source_type: str) -> None:
    """抓取 → 落盘 → 摄取。

    抓到的字节要落盘，理由与上传路径一致：摄取失败（常见于没配 embedding key）
    后用户重跑时不该再依赖那个站点还在线、还返回同样的内容。
    """
    async with SessionLocal() as bg_db:
        source = await bg_db.get(Source, source_id)
        if source is None:  # pragma: no cover — 建源与后台任务之间不该被删
            logger.warning("source %s 在抓取启动前已被删除", source_id)
            return
        try:
            payload = await fetch_for_ingest(url, source_type)
        except FetchError as exc:
            # FetchError 的 message 是写给用户看的，直接落库。
            await mark_failed(bg_db, source, str(exc))
            logger.warning("source %s 抓取失败：%s", source_id, exc)
            return
        except Exception:
            # 网络栈的意外异常（DNS 抖动、连接重置）不带用户可读信息，
            # 只给一句概括——细节留在日志里。
            logger.exception("source %s 抓取时发生未预期错误", source_id)
            await mark_failed(bg_db, source, "抓取时发生内部错误")
            return

        source.storage_path = storage.save_upload(payload, f"url{_suffix_for(source_type)}")
        source.size_bytes = len(payload)
        await bg_db.commit()
        await _ingest_now(bg_db, source_id, payload)


async def _ingest_with_payload(source_id: int, payload: bytes) -> None:
    """上传路径的后台任务体。"""
    async with SessionLocal() as bg_db:
        await _ingest_now(bg_db, source_id, payload)


async def _ingest_now(db: AsyncSession, source_id: int, payload: bytes) -> None:
    """在已开好的 session 里跑摄取管线。两条入口共用。"""
    source = await db.get(Source, source_id)
    if source is None:  # pragma: no cover — 建源与后台任务之间不该被删
        logger.warning("source %s 在摄取启动前已被删除", source_id)
        return
    try:
        await ingest(db, get_vector_engine(), source, payload)
    except IngestError:
        # 详情已由 ingest 写进 sources.error_message，这里只留一行索引
        logger.warning("source %s 摄取失败（见 error_message）", source_id)
    except Exception:
        logger.exception("source %s 摄取时发生未预期错误", source_id)


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    """建后台任务并保住强引用。

    asyncio 只持弱引用，GC 可能在任务跑完前把它回收掉，症状是
    「偶尔摄取没开始，也没报错」。
    """
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _suffix_for(source_type: str) -> str:
    """URL 建源落盘时的扩展名。

    只为让 storage 生成的路径可辨认；``save_upload`` 只取扩展名做净化，
    不按它选解析器（选解析器的是 sources.source_type）。
    """
    return ".pdf" if source_type == SourceType.PDF else ".html"


# 强引用集合，见 _schedule_ingest 的注释。
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _suffix(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()
