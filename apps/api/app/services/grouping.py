"""资料版本分组：判断「新上传的这份」是不是某份已有资料的新版本。

## 要解决的问题

同一份简历改过以后再传一次，库里就有两份内容高度相似的资料。它们各自切片、
各自索引，检索时**一起进候选池**——向量检索会把两版都召回来，模型收到互相
冲突的证据，于是可能选中旧版、或把两版混着编。

语义相似不等于事实有效：旧版可以和问题一样匹配，但已经不是当前答案。

所以要把它们归到一组，组内只有一份**生效版本**参与检索。

## 三层判定，逐级降级

1. **内容 hash 相同** → 完全相同的文件。上传入口直接拒（409）。
   （摄取失败的除外——那份一条切片都没有，重传是恢复动作，见
   :func:`find_duplicate_hash`。）
2. **正文相似度超阈值** → 同一份资料的另一个版本。归入该组。
   （候选池不足 :data:`MIN_CANDIDATES_FOR_GROUPING` 份时不归组——
   池子太小 TF-IDF 压不住模板词，见该常量的实测数据。）
3. 都不满足 → 自建新组。

## 为什么用 TF-IDF 余弦而不是朴素的 Jaccard

朴素 Jaccard 在这个场景会**误并不同人的简历**——两份不同简历的 token 集合
重叠极高：「项目经历」「工作经历」「教育背景」「任职时间」这类**结构模板词**
人人都有。

TF-IDF 的 IDF 项正好压掉它们：「项目经历」在这位用户的全部资料里都出现，
IDF 接近 0，权重可忽略；而「张建鹏」「13800138000」「字节跳动」这类
**识别性 token** 只在一份里出现，IDF 高，权重压倒性。

余弦而非 Jaccard：余弦对「文档长度差异」不敏感（前几片长短不一时
Jaccard 会被长度稀释），且便于叠加 IDF 权重。

## 为什么不用嵌入向量

上传时算相似度要多调一次嵌入服务，而嵌入服务**欠费是已知状态**
（见项目记忆里的 embedding-api-arrearage）。归组不能因为嵌入挂了就不工作——
用户传了文件却因为欠费而无法归组，是不可接受的失败。

## 相似度只看前 N 片

简历是结构化文档，**前几片就是抬头信息**（姓名、电话、邮箱、学历），
那是判断「同一个人」最稳定的信号。后面的项目描述改动很大，
用它判同组会把「同一个人改过简历」判成「两个人」。

## 阈值需要标定

:data:`SIMILARITY_THRESHOLD` 是按经验取的 0.6，**尚未用真实简历样本标定**。
换一份语料（技术文档、合同）应该重新标。标定方法见
``tests/test_grouping.py`` 里的说明。
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import jieba
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import WEB_SOURCE_TYPE, Source, SourceStatus

logger = logging.getLogger(__name__)

# jieba 默认往 stderr 打词典加载日志，在后台任务里会污染错误输出
jieba.setLogLevel(logging.WARNING)

# 相似度阈值：达到这个值就认为是「同一份资料的另一个版本」。
#
# **待标定**——0.6 是经验值，没有用真实简历样本标定过。
# 标定方法：取 N 对样本（同名同人的简历版本 / 不同人的同名简历），
# 算 TF-IDF 余弦，看正负样本的分界在哪，取中间偏保守的值。
SIMILARITY_THRESHOLD = 0.6

# 参与比较的切片数（前 N 片）。
#
# 8 片 × 512 字符 ≈ 4000 字符，足够覆盖简历抬头 + 联系方式 + 教育背景。
# 再多会吃到项目描述区，而那正是版本间差异最大的部分。
PROFILE_CHUNKS = 8

# 候选比较时最多看多少份历史资料。
#
# 单用户量级下这个上限用不上（几十份就够），但它防止「用户传了 500 份资料」
# 时每次上传都做 O(n) 比较——相似度计算不是免费的。
MAX_CANDIDATES = 200

# 候选池少于这么多份就**不归组**（自建新组）。
#
# ## 为什么池子小了会误判
#
# TF-IDF 的 IDF 项靠**文档频率**算：「项目经历」在这位用户的全部资料里
# 都出现 → df 高 → IDF 低 → 权重可忽略。而「张建鹏」只在一份里出现 →
# IDF 高 → 权重压倒性。**这套机制的前提是池子里有多份资料**。
#
# 池子只有 1 份时所有 token 的 IDF 相同，TF-IDF 退化成词频余弦，
# 模板词压不下去——不同人的同模板简历会越阈值。
#
# 实测（tests/test_grouping.py 的语料，同模板不同人）：
#
#   池 1 份 → 负样本 0.6945（越阈值，误并）
#   池 2 份 → 负样本 0.6563（越阈值，误并）
#   池 3 份 → 负样本 0.6027（越阈值，误并）
#   池 4 份 → 负样本 0.5611（低于阈值，安全）
#
# 正样本（同一人的不同版本）在池 4 份时是 0.82–0.98，不受这个下限影响。
#
# ## 为什么宁可漏归不可误并
#
# 误并的代价远大于漏归：误并会让**新上传的那份**顶掉用户原有的资料
# （摄取成功后切换生效版），用户原来的资料静默退出检索池——而漏归
# 只是两份资料并存，检索时可能互相干扰，用户自己能看出来。
#
# 所以候选池不足就不归组。代价是「用户只有 1–3 份资料时，上传新版本
# 不会自动归组」——这是可接受的：用户可以手动用「设为生效版」切换。
MIN_CANDIDATES_FOR_GROUPING = 4


def content_hash(payload: bytes) -> str:
    """原始文件的 sha256 十六进制摘要。

    **只用来识别「完全相同的文件」，不用来判断哪个版本权威**——
    权威性由 ``is_active`` 决定。两份 hash 相同说明它们是同一份内容，
    不说明哪份更新（用户可能故意重传同一份来覆盖）。
    """
    return hashlib.sha256(payload).hexdigest()


def version_label(group_id: int | None, version_no: int) -> str:
    """版本标记的**唯一真源**。

    不参与分组（``group_id`` 为 None）**或第 1 版**→ 空串；否则 ``第 N 版``。

    ## 为什么要有这个函数

    拼法在三个地方要用：资料列表响应、引用表（SSE）、历史报告的引用回查。
    三处各写一次 f-string 必然漂移——一处写「第2版」一处写「第 2 版」，
    用户看到同一份资料在两个页面显示不同标记。

    前端**不拼**这个字符串（``SourceResponse.version_label`` 由后端算好）：
    前端拼就要复制这份规则，而规则会变。

    ## 为什么第 1 版不标

    每份上传的资料都会自建一个组（见 ``source_versions._ensure_group``），
    所以「组里只有自己」是**最常见的状态**，不是例外。若第 1 版也标
    「第 1 版」，表格每一行都挂着一个「第 1 版」徽章、每条引用角标都带
    「（第 1 版）」、模型看到的证据块标题是「xxx.pdf（第 1 版）」——
    一个不携带任何信息的标签刷满全站。

    第 1 版**不是「没有版本信息」**，而是「这一份是该组的第 1 版」。
    它是旧版时前端另有「旧版」徽章标着（见 ``SourceTable`` 的
    ``VersionCell``），是生效版时用户看到的就是「—」。两者都不需要
   「第 1 版」这三个字。

    所以只有 **第 2 版及以上**才带标记——那时「这是第几版」才真的
    在回答一个用户关心的问题（这份资料被改过几次）。
    """
    if group_id is None or version_no <= 1:
        return ""
    return f"第 {version_no} 版"


def tokenize(text: str) -> list[str]:
    """jieba 分词，去掉纯标点。

    与 :mod:`app.services.bm25` 的分词规则一致（同一套中文切词），
    但**不做去重**——TF-IDF 要的是词频，不是词集。
    """
    return [tok for tok in jieba.cut(text) if any(ch.isalnum() for ch in tok)]


@dataclass(frozen=True, slots=True)
class Profile:
    """一份资料的「抬头画像」——前 N 片的词频表。"""

    source_id: int
    group_id: int | None
    version_no: int
    counts: dict[str, int]
    """词 → 词频。"""


@dataclass(frozen=True, slots=True)
class GroupingDecision:
    """一份新资料的归组判定结果。"""

    group_id: int | None
    """归入的组 id。None = 需要新建组。"""
    version_no: int
    """组内版本号。从 1 起。"""
    is_active: bool
    """**插入时**是否生效。

    新组的第一份 → True（组里只有它）。
    已有组的新版本 → False，**等摄取成功后才切成 True**——
    摄取失败时旧版仍是生效版，用户不会同时失去两份可检索资料。
    """
    matched_source_id: int | None = None
    """命中相似度阈值的那份资料 id。没命中为 None。"""
    similarity: float = 0.0
    """命中时的相似度。没命中为 0.0。"""


def profile_counts(text: str) -> dict[str, int]:
    """词频表。"""
    counts: dict[str, int] = {}
    for tok in tokenize(text):
        counts[tok] = counts.get(tok, 0) + 1
    return counts


def _tfidf(counts: dict[str, int], idf: dict[str, float]) -> dict[str, float]:
    """词频 → TF-IDF 向量（未归一化）。

    用 ``1 + ln(tf)`` 而不是原始 tf：原始 tf 让高频词（出现 50 次的
    「负责」）压过一切，而它对「是不是同一个人」毫无信息量。
    """
    return {tok: (1.0 + math.log(count)) * idf.get(tok, 0.0) for tok, count in counts.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """余弦相似度。空向量或无交集返回 0.0。"""
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_idf(profiles: Sequence[Profile], new_counts: dict[str, int]) -> dict[str, float]:
    """从候选集 + 新资料算 IDF。

    **文档频率在候选集上统计**——「项目经历」在这位用户的全部资料里都出现，
    IDF 接近 0；「张建鹏」只在一份里出现，IDF 高。这就是压掉结构模板词、
    保留识别性 token 的机制。

    平滑用 ``ln((N+1)/(df+1)) + 1``，保证 df=0 的词（只在新资料里出现）
    也有正权重。

    ## 为什么 IDF 要**随候选集**重算

    不同用户的资料构成完全不同——「张建鹏」在 A 用户的库里 IDF 高，
    在 B 用户的库里可能也高（只有一份资料时所有词 IDF 相同）。
    固定一套 IDF 会让相似度在不同用户间不可比。所以每次比较都重算。
    """
    total_docs = len(profiles) + 1
    df: dict[str, int] = {}
    for profile in profiles:
        for tok in profile.counts:
            df[tok] = df.get(tok, 0) + 1
    for tok in new_counts:
        df[tok] = df.get(tok, 0) + 1

    return {tok: math.log((total_docs + 1) / (count + 1)) + 1.0 for tok, count in df.items()}


def similarity(new_counts: dict[str, int], profiles: Sequence[Profile]) -> tuple[float, int | None]:
    """新资料与候选集中**最相似**的那份的相似度。

    返回 ``(相似度, 命中的 source_id)``。没命中返回 ``(0.0, None)``。

    ## 为什么取最大值而不是平均值

    同一个人可能有多份历史资料（v1、v2）。新的一份只要与**其中任意一份**
    高度相似，就该归入那个组。取平均会把「与 v1 像、与 v2 不像」稀释掉。
    """
    if not profiles:
        return 0.0, None

    idf = build_idf(profiles, new_counts)
    new_vec = _tfidf(new_counts, idf)

    best_score = 0.0
    best_id: int | None = None
    for profile in profiles:
        score = cosine(new_vec, _tfidf(profile.counts, idf))
        if score > best_score:
            best_score = score
            best_id = profile.source_id
    return best_score, best_id


async def load_profiles(db: AsyncSession, user_id: int) -> list[Profile]:
    """取用户的历史资料做候选，各自的前 N 片词频。

    **一次查完**（一条 SQL + 一次切片查询），不做 N+1。

    只取前 :data:`PROFILE_CHUNKS` 片——理由见模块 docstring。
    """
    sources = list(
        await db.scalars(
            select(Source)
            .where(Source.user_id == user_id, Source.source_type != WEB_SOURCE_TYPE)
            .order_by(Source.created_at.desc())
            .limit(MAX_CANDIDATES)
        )
    )
    if not sources:
        return []

    from app.models.source import DocumentChunk

    source_ids = [s.id for s in sources]
    rows = (
        await db.execute(
            select(DocumentChunk.source_id, DocumentChunk.content)
            .where(DocumentChunk.source_id.in_(source_ids))
            .order_by(DocumentChunk.source_id, DocumentChunk.chunk_index)
        )
    ).all()

    # 按 source_id 聚起来，每份只留前 N 片。
    texts: dict[int, list[str]] = {}
    for source_id, content in rows:
        bucket = texts.setdefault(source_id, [])
        if len(bucket) >= PROFILE_CHUNKS:
            continue
        bucket.append(content)

    profiles: list[Profile] = []
    for source in sources:
        chunks = texts.get(source.id, [])
        counts = profile_counts("\n".join(chunks))
        profiles.append(
            Profile(
                source_id=source.id,
                group_id=source.group_id,
                version_no=source.version_no,
                counts=counts,
            )
        )
    return profiles


async def candidate_pool_size(db: AsyncSession, user_id: int) -> int:
    """候选池里**有效**的份数——词频表非空的那几份。

    ## 为什么只数非空的

    摄取失败（嵌入服务欠费）或还没开始摄取的资料，词频表是空的——
    它们**对 IDF 毫无贡献**：df 不变、每个 token 的 IDF 也不变。
    把它们算进池子会让「池子够大」这个门槛**说谎**：

    门槛是 4 份（实测 3 份时不同人的同模板简历会越阈值）。
    用户有 3 份真资料 + 1 份 failed 的行 → 按份数算是 4 → 门槛放行，
    但实际有效池是 3 → 误判照样发生。

    failed 行很常见（嵌入服务欠费是已知状态），所以这条不是理论风险。
    """
    sources = list(
        await db.scalars(
            select(Source)
            .where(Source.user_id == user_id, Source.source_type != WEB_SOURCE_TYPE)
            .order_by(Source.created_at.desc())
            .limit(MAX_CANDIDATES)
        )
    )
    if not sources:
        return 0

    from app.models.source import DocumentChunk

    source_ids = [s.id for s in sources]
    # 只问「有多少份有切片」，不取正文——正文由 load_profiles 取。
    rows = (
        await db.execute(
            select(DocumentChunk.source_id)
            .where(DocumentChunk.source_id.in_(source_ids))
            .group_by(DocumentChunk.source_id)
        )
    ).all()
    return len(rows)


async def resolve_grouping(
    db: AsyncSession,
    user_id: int,
    *,
    profile_text: str,
) -> GroupingDecision:
    """判定一份新资料归到哪一组。

    返回 :class:`GroupingDecision`：

    - 新组 → ``group_id=None``、``version_no=1``、``is_active=True``
    - 归入已有组 → ``group_id=该组``、``version_no=组内最大+1``、``is_active=False``
      （**等摄取成功后才切成 True**）

    ## 为什么命中已有组时 is_active=False

    摄取可能失败（嵌入服务欠费是已知状态）。若插入时就生效，
    失败后用户会同时失去新旧两份可检索资料——旧版被顶掉，新版又没建成。
    所以「新版本先建后切」：插入时不生效，摄取成功才切换。
    """
    new_counts = profile_counts(profile_text)
    if not new_counts:
        # 正文为空（解析失败或空文件）——无从判定，归新组。
        return GroupingDecision(group_id=None, version_no=1, is_active=True)

    profiles = await load_profiles(db, user_id)
    # 只数**词频表非空**的候选——空表对 IDF 没有贡献，算进池子会让
    # 门槛说谎（详见 :func:`candidate_pool_size`）。
    effective_pool = sum(1 for p in profiles if p.counts)
    if effective_pool < MIN_CANDIDATES_FOR_GROUPING:
        # 候选池太小，TF-IDF 压不住模板词（见 MIN_CANDIDATES_FOR_GROUPING
        # 的实测数据）——不同人的同模板文档会越阈值。
        # 宁可漏归不可误并：误并会让新上传的那份顶掉用户原有的资料。
        logger.info(
            "候选池只有 %d 份，不足 %d 份，本次不归组",
            len(profiles),
            MIN_CANDIDATES_FOR_GROUPING,
        )
        return GroupingDecision(group_id=None, version_no=1, is_active=True)

    score, matched_id = similarity(new_counts, profiles)

    if score < SIMILARITY_THRESHOLD or matched_id is None:
        return GroupingDecision(group_id=None, version_no=1, is_active=True)

    matched = next((p for p in profiles if p.source_id == matched_id), None)
    if matched is None or matched.group_id is None:
        # 命中的那份还没归组（老资料）。归到它那一组不成立——
        # 它没有 group_id 可继承。只能自建新组。
        #
        # 为什么不把老资料一起拉进组：老资料没有 profile 缓存，
        # 重新归组它需要重新解析正文，代价高且可能误并。
        # 归组只对新上传的资料生效（见迁移文件的说明）。
        return GroupingDecision(group_id=None, version_no=1, is_active=True)

    # 命中的组里已有多少版本 → 新版本号
    group_versions = await db.scalars(
        select(Source.version_no).where(
            Source.group_id == matched.group_id,
            Source.user_id == user_id,
        )
    )
    next_version = max(list(group_versions), default=0) + 1

    logger.info(
        "资料归组：source %s 归入组 %s（第 %d 版），相似度 %.3f",
        matched_id,
        matched.group_id,
        next_version,
        score,
    )
    return GroupingDecision(
        group_id=matched.group_id,
        version_no=next_version,
        is_active=False,
        matched_source_id=matched_id,
        similarity=score,
    )


# ── 生效版本切换 ─────────────────────────────────────────────


async def activate_version(db: AsyncSession, source: Source) -> None:
    """把某份资料设为其所在组的**生效版本**。

    组内其他版本转归档（``is_active=False``）。

    ## 顺序：先归档旧的，再激活新的

    ``ux_sources_group_active`` 是部分唯一索引，同一个 ``group_id`` 下
    至多一条 ``is_active=1``。先激活新的会撞唯一约束——所以必须**先**
    把旧的置 False，**再**把新的置 True。

    两条 UPDATE 在同一事务里：中间态（新的还没激活、旧的已归档）不会
    被别的连接看到。

    ## 为什么不在这里 commit

    调用方决定事务边界。摄取路径要等「新版本全部索引完成」才一起提交；
    手动切换端点则在自己的事务里提交。**分开提交会出现「新版本还没
    建好，旧版已经归档」的窗口**——那段时间用户一份可检索的资料都没有。
    """
    if source.group_id is None:
        # 未归组的资料：它本身就是生效版，什么都不用改。
        source.is_active = True
        return

    await db.execute(
        update(Source)
        .where(
            Source.group_id == source.group_id,
            Source.user_id == source.user_id,
            Source.id != source.id,
            Source.is_active.is_(True),
        )
        .values(is_active=False)
    )
    source.is_active = True


async def activate_if_newest(db: AsyncSession, source: Source) -> bool:
    """摄取成功后接管生效位——但**只在它是组内最新的一版时**。

    ## 为什么不能按「摄取完成顺序」决定

    摄取是**后台并发**跑的：用户连传 v2 与 v3，两份的摄取完成顺序
    不确定（嵌入服务延迟、文件大小、切片数都可能影响）。

    若「谁最后完成谁生效」，v2 的摄取若最后完成，它会顶掉已经生效的
    v3——用户在检索的是**旧版**，而新版躺在归档里，且没有任何错误提示。

    ``version_no`` 存在的意义正是表达「新旧」：**新版本号更大**。
    所以决胜要按 ``version_no``，不按完成时间。

    ## 判据

    组内已索引的版本里，``version_no`` 最大的是最新的。当前这份不是
    最大的 → 有人在它之后上传过，那份才是生效版，这份不该抢。

    **「已索引」是判据的一半**：组里可能有一份 v4 还在摄取中（未索引），
    它不该阻止 v3 成为生效版——否则组里会短暂没有任何生效版。

    ## 返回值

    True = 接管了生效位；False = 组内已有更新的版本生效，这份保持归档。
    """
    if source.group_id is None:
        # 未归组的资料：它本身就是生效版。
        source.is_active = True
        return True

    newest_id = await db.scalar(
        select(Source.id)
        .where(
            Source.group_id == source.group_id,
            Source.user_id == source.user_id,
            Source.status == SourceStatus.INDEXED,
        )
        .order_by(Source.version_no.desc())
        .limit(1)
    )
    if newest_id is not None and newest_id != source.id:
        # 组里有一份更新且已建成的版本——它才是生效版，这份保持归档。
        return False

    await deactivate_others(db, source)
    source.is_active = True
    return True


async def deactivate_others(db: AsyncSession, source: Source) -> None:
    """把同组其他版本全部归档，但**不动** source 自己的 is_active。

    摄取成功路径用它：新版本插入时是 ``is_active=False``（避免摄取失败
    时旧版被顶掉），摄取完成后才归档旧版、把它设为生效。

    与 :func:`activate_version` 的差别：那个会**设置** ``source.is_active=True``，
    这个不会——调用方自己控制 source 的状态。
    """
    if source.group_id is None:
        return
    await db.execute(
        update(Source)
        .where(
            Source.group_id == source.group_id,
            Source.user_id == source.user_id,
            Source.id != source.id,
            Source.is_active.is_(True),
        )
        .values(is_active=False)
    )


async def promote_after_delete(db: AsyncSession, source: Source) -> None:
    """删掉生效版后，让组内剩下的版本接管生效位。

    ## 为什么必须接管

    检索的候选集是「组内 ``is_active=True`` 的那些」
    （``Source.list_active_owned``）。删掉生效版而不接管的话，
    组里剩下的版本**全是 ``is_active=False``**——它们还在库里、还能
    点开看，但**一份都召不回来**。用户看到的是「资料还在，搜不到」，
    而资料页只给它一个「旧版」徽章，不解释为什么。

    这是「只检索生效版」这条规则引入的行为回归：改动之前没有版本概念，
    删掉一份剩下的都还在检索池里。

    ## 接管的挑谁

    组内 ``version_no`` **最大**且**已建成索引**的那份——它是最新的一版，
    最接近用户删除前想要的东西。「最新」比「最老」更符合直觉：用户删掉
    v2 之后想要的大概率是 v1（唯一剩下的），而删掉 v1 之后想要的是 v3。

    ## 为什么必须过滤未索引的版本

    生效位是检索候选集的一员。**没建成索引的版本占了这个位置**，
    等于「整组都搜不到」——它一条切片都没有，而它顶掉的那份是唯一
    能用的。摄取失败（嵌入服务欠费是已知状态）留下的行就是这种。

    与 :func:`app.services.source_versions.activate` 的 ``NotIndexableError``
    守的是同一件事：一个地方能进，另一个地方也得能进。

    ## 只在真的需要接管时才动

    组里还有别的生效版时什么都不做——那是正常状态（删掉的是一个归档版）。
    """
    if source.group_id is None:
        return

    # 组里还有别的生效版吗？有就不需要接管。
    others = await db.scalars(
        select(Source.id).where(
            Source.group_id == source.group_id,
            Source.user_id == source.user_id,
            Source.id != source.id,
            Source.is_active.is_(True),
        )
    )
    if list(others):
        return

    # 没有生效版了 → 让 version_no 最大的**已索引**那份接管。
    successor_id = await db.scalar(
        select(Source.id)
        .where(
            Source.group_id == source.group_id,
            Source.user_id == source.user_id,
            Source.id != source.id,
            Source.status == SourceStatus.INDEXED,
        )
        .order_by(Source.version_no.desc())
        .limit(1)
    )
    if successor_id is None:
        return

    await db.execute(
        update(Source).where(Source.id == successor_id).values(is_active=True)
    )
    logger.info(
        "删除了组 %s 的生效版，改由 source %s 接管",
        source.group_id,
        successor_id,
    )


async def find_duplicate_hash(
    db: AsyncSession,
    user_id: int,
    digest: str,
) -> Source | None:
    """找同用户下 content_hash 相同**且已建成**的资料。

    用来在上传入口拒绝「完全相同的文件重复上传」。

    **只查 content_hash 相同**——不查相似度。近似但不同的文件应该
    归为新版本而不是被拒。

    ## 拦的是「已建成索引」的那份

    已建成索引的行说明这份资料**真的存在且可用**——再传一次就是
    重复上传，拦 409。

    ## 为什么不拦「还没建成索引」的

    没有切片的资料，重传同一份文件是**恢复动作**，不是「重复上传」——
    ``app/services/ingest.py`` 的 ``mark_failed`` docstring 明写
    「用户重传即刻恢复」。

    未建成索引的行有两类：

    - ``failed``：摄取失败（嵌入服务欠费是已知状态）时留下的那行，
      一条切片都没有。
    - ``pending`` / ``parsing`` / ``chunking`` / ``embedding``：进程重启
      丢掉后台摄取任务时留下的那行（``gateway/sources.py`` 的模块
      docstring 记着这个已知缺口）。它会永远停在 pending，
      用户看到的是「一直在增量切片中」。

    若把这些也算重复，用户会遇到死路：重传被 409 拒，而唯一能解开的
    办法是先手动删掉那份资料——而 409 的文案「这份资料已经上传过了」
    只字未提要删。

    「误点两次上传」造成的那条 pending 由
    :func:`app.services.source_versions.supersede_stale_pending` 处理
    ——它把那条作废，而不是把新上传拒掉。
    """
    stmt = select(Source).where(
        Source.user_id == user_id,
        Source.content_hash == digest,
        Source.status == SourceStatus.INDEXED,
    )
    return await db.scalar(stmt)


async def supersede_stale_pending(db: AsyncSession, user_id: int, digest: str) -> int:
    """把同 hash 的「未建成索引」行标成 superseded，返回作废了几条。

    ## 为什么需要它

    用户误点两次上传（或客户端重试）时，两条内容完全相同的 Source
    都会建出来、各自切片各自索引，最后**两份都生效、都进检索池**——
    检索会召回两份一模一样的证据，模型把同一段话当成两个独立来源
    互相印证。

    而 :func:`find_duplicate_hash` 不能直接拦 pending——那会把
    「进程重启丢掉后台摄取任务」后的恢复路径也堵死（重传被 409 拒，
    用户只能手动删僵尸行）。

    两者的区别是**状态**，处理方式就该不同：

    - 已建成索引 → **拒**（409）：它是真的存在，不该再来一份。
    - 未建成索引 → **作废**（superseded）：它什么都不是，让新的接管。

    ## 作废 = 标成 superseded

    不是删行——删行会让「这份资料失败过」的历史消失，而失败原因
    （嵌入服务欠费）是用户需要看到的诊断信息。

    ``status=superseded`` 的行不生效、不进检索池、不算重复
    （:func:`find_duplicate_hash` 只认 indexed）。
    """
    rows = list(
        await db.scalars(
            select(Source).where(
                Source.user_id == user_id,
                Source.content_hash == digest,
                Source.status != SourceStatus.INDEXED,
                Source.status != SourceStatus.SUPERSEDED,
            )
        )
    )
    if not rows:
        return 0

    for row in rows:
        row.status = SourceStatus.SUPERSEDED
        row.is_active = False
    await db.commit()
    logger.info(
        "作废 %d 条同内容的未建成索引资料（用户 %s）——重复上传或僵尸行",
        len(rows),
        user_id,
    )
    return len(rows)
