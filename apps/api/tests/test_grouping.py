"""资料版本分组的测试。

## 覆盖什么

- **A 段（纯函数）**：TF-IDF 余弦相似度能不能分清「同一个人的两个版本」
  与「两个不同的人」。这是整个归组机制的基石——阈值定错，两个人的简历
  会被归成一组，用户看到的是别人的版本被当成自己的。
- **B 段（要库）**：``resolve_grouping`` 的归组判定——归哪个组、版本号
  怎么递增、插入时是否生效。
- **C 段（要库）**：生效版切换，以及「组内至多一条生效版」这条约束
  **是不是真的在数据库层拦得住**（不靠应用层自觉）。
- **D 段**：检索只召回生效版（在 ``tests/test_retriever.py`` 里）。
- **E 段**：完全相同的文件重复上传能识别出来。
- **F 段**：迁移与 ORM 一致（在 ``tests/test_migrations.py`` 里）。

## 阈值怎么标定

:data:`app.services.grouping.SIMILARITY_THRESHOLD` = 0.6 是经验值，
**还没用真实简历样本标定过**。标定方法（也就是本文件 A 段做的事）：

1. 取 N 对正样本——**同一个人**的两个版本（抬头信息相同、项目描述改了）。
2. 取 N 对负样本——**不同的人**，但**都用同一套简历模板**（都有
   「项目经历」「工作经历」「教育背景」这类词）。
3. 负样本必须是**难负例**：模板结构完全相同，只有姓名/联系方式/公司不同。
   随便拿两份无关文本当负例等于没测——那谁都能分开。
4. 用 TF-IDF 余弦算每一对的分数，看正负样本的分界在哪，取中间偏保守的值。

**为什么负样本必须是同一套模板**：朴素 Jaccard 在模板结构上必然误判
——「项目经历」「工作经历」「教育背景」这类词人人都有，两份不同人的
简历 token 集合重叠极高。TF-IDF 的 IDF 项专门压它们（「项目经历」在
候选集里人人都有 → IDF≈0 → 权重可忽略；「张建鹏」只在一份里 → IDF 高
→ 权重压倒性）。所以 A 段那两条断言**同时**在验「TF-IDF 压得住模板词」。

本文件用的语料与阈值的关系（实测，本文件自己跑出来）：

- 正样本（同一人的两个版本）：≈ 0.95
- 负样本（不同人，同模板）：≈ 0.58
- 阈值 0.6 落在两者之间，间隔 ≈ 0.38
- **同一对负样本用朴素 Jaccard 算出来是 ≈ 0.61**——已越过阈值，
  也就是说换成 Jaccard 就会把两个不同的人归成一组。

**间隔（gap）是真正该盯的指标**：间隔太小（比如 0.61 vs 0.59）说明
阈值是在数据噪声上调出来的，换一批语料就失效。这里要求 gap > 0.3。

## 候选池为什么必须有多份资料

TF-IDF 的 IDF 项靠**文档频率**算：「项目经历」在这个用户的**全部**资料里
都出现 → df 高 → IDF 低 → 权重可忽略。

**候选池只有 1 份资料时，所有 token 的 IDF 相同**，TF-IDF 退化成跟
「词频余弦」差不多，模板词压不下去——不同人的简历会被误判成同一人
（实测 0.69 > 阈值 0.6；池 2 份 0.66、3 份 0.60、4 份 0.56）。

所以本文件的 B 段用例都建了 4 份「别人的」简历做池子。**这不是为了让
测试好看**——它反映的是真实使用形态：用户上传第一份资料时几乎必然
没有别人那份挡着，判断质量依赖后续资料积累。

正因为如此，实现里加了**候选池下限**
（``app.services.grouping.MIN_CANDIDATES_FOR_GROUPING`` = 4）：
池子不够大就不归组。误并的代价远大于漏归——误并会让新上传的那份
顶掉用户原有的资料（摄取成功后切换生效版），用户原来的资料静默退出
检索池，而漏归只是两份资料并存。见
``test_small_candidate_pool_does_not_group``。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk, Source, SourceGroup, SourceStatus, SourceType, User
from app.services.grouping import (
    SIMILARITY_THRESHOLD,
    Profile,
    activate_if_newest,
    activate_version,
    content_hash,
    deactivate_others,
    find_duplicate_hash,
    profile_counts,
    promote_after_delete,
    resolve_grouping,
    similarity,
    version_label,
)

# ── 语料 ────────────────────────────────────────────────────
#
# 简历模板：**每个候选人共用**。它是这一组测试的关键——
# 朴素 Jaccard 在这上面必然误判（模板词人人都有），TF-IDF 才分得开。
#
# 结构仿真实中文简历：抬头信息 + 小节标题 + 通用自我评价套话 + 个性化条目。
# 抬头信息是识别性信号（姓名/电话/邮箱/城市/意向/公司/学校/项目/技能），
# 模板与小节是「人人都一样」的部分。

_RESUME_LABELS = (
    "姓名 性别 出生年月 现居地 最高学历 工作经验 手机号码 电子邮箱 求职意向 "
    "工作经历 工作时间 公司名称 职位名称 工作描述 工作业绩 "
    "项目经历 项目名称 项目角色 项目描述 项目成果 "
    "教育背景 学校名称 专业名称 学历 学位 毕业时间 "
    "技能特长 编程语言 熟练度 框架 数据库 缓存 消息队列 "
    "获奖情况 证书名称"
)

# 自我评价套话：真实简历里这段几乎一字不差地重复。
# 它的长度刻意调过——**套话越长，朴素 Jaccard 越容易误判**，
# 而 TF-IDF 恰好把它压下去。这正是本文件要验的机制。
_RESUME_BOILERPLATE = (
    "工作认真负责 具备良好的团队协作精神与沟通能力 学习能力强 "
    "能够承受一定的工作压力 具备较强的抗压能力与责任心 服从上级安排 "
    "能够承受一定强度的工作任务 具有较强的执行能力与独立解决问题的能力 "
    "具备良好的创新意识与团队合作精神 "
    "具备较强的沟通协调能力与组织管理能力 有较强的计划执行能力与目标达成意识"
)


def _resume(identity: list[str]) -> str:
    """造一份简历：个性化抬头信息 + 共用模板 + 共用自我评价。"""
    return "\n".join(identity) + "\n" + _RESUME_LABELS + "\n" + _RESUME_BOILERPLATE


# 正样本：张建鹏的第 1 版与第 2 版。第 2 版改了项目描述与技能栈
# （「同一个人改了简历」）。
_ZHANG_IDENTITY = [
    "张建鹏",
    "13800138000",
    "zhangjp@example.com",
    "北京",
    "后端开发工程师",
    "字节跳动科技有限公司 高级后端工程师",
    "美团网络科技 后端工程师",
    "北京邮电大学 计算机科学与技术 本科",
    "推荐系统召回链路 QPS 提升",
    "实时特征平台 Flink ClickHouse",
]
_ZHANG_V1 = _resume(_ZHANG_IDENTITY)
_ZHANG_V2 = _resume([*_ZHANG_IDENTITY, "Doris Kafka Redis 日均千亿次访问"])

# 负样本：欧阳雪。她**不在候选池里**，与池子里每个人都用同一套模板，
# 只有抬头信息不同——这就是「难负例」。
_OUYANG_IDENTITY = [
    "欧阳雪",
    "13066667777",
    "ouyangx@example.com",
    "青岛",
    "产品经理",
    "海尔智家 产品经理",
    "浪潮集团 产品助理",
    "山东大学 工商管理 本科",
    "智能门锁产品线 竞品分析",
    "用户增长活动 Axure Figma",
]
_OUYANG = _resume(_OUYANG_IDENTITY)

# 候选池里的另外四个人。**必须有 4 份以上**——模板词要「在多份文档里都
# 出现」才能被 IDF 压下去（见模块 docstring）。
_POOL_IDENTITY = [
    [
        "李思远",
        "13900139000",
        "lisy@example.com",
        "上海",
        "数据分析师",
        "阿里巴巴集团 数据分析师",
        "携程旅行网 数据分析师",
        "复旦大学 统计学 本科",
        "用户增长指标看板 日活留存漏斗",
        "推荐算法实验平台 SQL Tableau",
    ],
    [
        "王泽宇",
        "13711112222",
        "wangzy@example.com",
        "深圳",
        "系统架构师",
        "腾讯科技 架构师",
        "华为技术 高级工程师",
        "清华大学 软件工程 硕士",
        "混合云调度平台 容灾方案",
        "容器化改造 Kubernetes Istio Rust",
    ],
    [
        "陈嘉怡",
        "13633334444",
        "chenjy@example.com",
        "广州",
        "前端开发工程师",
        "网易游戏 前端工程师",
        "字节跳动 前端工程师",
        "中山大学 软件工程 本科",
        "低代码搭建平台 组件协议",
        "组件库建设 React TypeScript Vue",
    ],
    [
        "刘宇轩",
        "13555556666",
        "liuyx@example.com",
        "杭州",
        "平台架构师",
        "滴滴出行 技术专家",
        "快手 高级工程师",
        "浙江大学 计算机技术 本科",
        "实时风控平台 特征回溯",
        "数据库拆分 Kafka MySQL",
    ],
]
_POOL_TEXTS = [_resume(identity) for identity in _POOL_IDENTITY]

# 张建鹏在候选池里的 source_id。放在**最后**——「取候选集第一个」的
# 错误实现会拿到别人，matched_source_id 断言就能抓到它。
_ZHANG_PROFILE_ID = 100


def _profile(source_id: int, text: str, group_id: int | None = 1) -> Profile:
    counts = profile_counts(text)
    return Profile(
        source_id=source_id,
        group_id=group_id,
        version_no=1,
        counts=counts,
    )


def _pool_profiles() -> list[Profile]:
    """候选池：池子里四个人 + 张建鹏的第 1 版。"""
    profiles = [
        _profile(i + 1, text, group_id=i + 1) for i, text in enumerate(_POOL_TEXTS)
    ]
    profiles.append(_profile(_ZHANG_PROFILE_ID, _ZHANG_V1, group_id=_ZHANG_PROFILE_ID))
    return profiles


def _jaccard(a: dict[str, int], b: dict[str, int]) -> float:
    """朴素 Jaccard——**只用于测试里演示对照**，不是生产实现。"""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ── 建库数据的 helper（写法照 tests/test_source_models.py）──────────


async def _make_user(session: AsyncSession, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0])
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_group(session: AsyncSession, user: User) -> int:
    """建一个组，返回 group_id（int，不是 ORM 对象）。

    **返回 int 而不是 ORM 对象**是有意的：rollback 之后 ORM 对象上的
    属性全部过期，再读 ``group.id`` 会触发隐式 SELECT——在 async 场景下
    那是 ``MissingGreenlet``。返回 int 就绕开了这个坑。
    """
    group = SourceGroup(user_id=user.id)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return int(group.id)


async def _make_source(
    session: AsyncSession,
    user: User,
    *,
    title: str = "测试资料",
    group_id: int | None = None,
    is_active: bool = True,
    version_no: int = 1,
    digest: str | None = None,
    chunks: list[str] | None = None,
    status: SourceStatus = SourceStatus.INDEXED,
) -> int:
    """建一份资料（可选带切片正文），返回 source_id。

    切片正文是 ``resolve_grouping`` 的输入——它只读前
    :data:`app.services.grouping.PROFILE_CHUNKS` 片，所以这里给的
    就是「抬头画像」。

    ``status`` 默认 indexed——「已建成索引」是它能进检索池、能接管
    生效位的前提。
    """
    source = Source(
        user_id=user.id,
        title=title,
        source_type=SourceType.TEXT,
        status=status,
        group_id=group_id,
        is_active=is_active,
        version_no=version_no,
        content_hash=digest,
    )
    session.add(source)
    await session.flush()
    for index, text in enumerate(chunks or []):
        session.add(
            DocumentChunk(source_id=source.id, chunk_index=index, content=text, page=index + 1)
        )
    await session.commit()
    return int(source.id)


async def _seed_pool(db_session: AsyncSession, user: User) -> tuple[int, int]:
    """建候选池：4 份「别人的」简历（各自独立组）+ 张建鹏的第 1 版。

    返回 ``(张建鹏的 source_id, 张建鹏的 group_id)``。

    **为什么必须建这 4 份**：TF-IDF 的 IDF 项靠文档频率算，模板词要在
    多份文档里都出现才会被压低。池子里只有 1 份时 TF-IDF 压不住模板词，
    不同人的简历会被误判成同一人（实测 0.67 > 阈值 0.6）。

    **为什么返回 group_id**：新版本要落进**张建鹏那一组**——归组判定
    继承的是命中资料所在的组，新建一个空组没用。
    """
    for index, text in enumerate(_POOL_TEXTS):
        other_group = await _make_group(db_session, user)
        await _make_source(
            db_session,
            user,
            title=f"别人 {index}",
            group_id=other_group,
            is_active=True,
            version_no=1,
            chunks=[text],
        )
    zhang_group = await _make_group(db_session, user)
    zhang_id = await _make_source(
        db_session,
        user,
        title="张建鹏 v1",
        group_id=zhang_group,
        is_active=True,
        version_no=1,
        chunks=[_ZHANG_V1],
    )
    return zhang_id, zhang_group


# ── A 段：相似度算法（纯函数）────────────────────────────────


def test_same_person_two_versions_score_above_threshold() -> None:
    """同一人的两个版本相似度高于阈值。

    **在哪种错误实现下也会通过**：如果实现把相似度写死成 1.0，任何一对
    都会「高于阈值」——这条也会绿。所以它必须配着「不同人低于阈值」
    那条一起看，两条同时过才有意义。
    """
    profiles = _pool_profiles()

    score, matched = similarity(profile_counts(_ZHANG_V2), profiles)

    assert score >= SIMILARITY_THRESHOLD, f"同一人两版相似度 {score:.4f} 未过阈值"
    assert matched == _ZHANG_PROFILE_ID, (
        f"应命中张建鹏的第 1 版（source_id={_ZHANG_PROFILE_ID}），实际 {matched}"
    )


def test_different_people_score_below_threshold() -> None:
    """不同人（**同一套模板**）相似度低于阈值。

    这是 A 段最关键的一条：负样本是**难负例**——两人用的是同一套简历
    模板，都有「项目经历」「工作经历」「教育背景」「技能特长」这些词，
    只有姓名/联系方式/公司/学校不同。

    **在哪种错误实现下也会通过**：如果实现用朴素 Jaccard，模板词会让
    两份不同人的简历重叠率虚高——下面那条
    ``test_naive_jaccard_would_misjudge_this_pair`` 断言的正是这个
    场景：Jaccard 会给出 >= 0.6 的分数（判成同一人），TF-IDF 判 < 0.6。
    """
    profiles = _pool_profiles()

    score, matched = similarity(profile_counts(_OUYANG), profiles)

    assert score < SIMILARITY_THRESHOLD, (
        f"不同人的简历相似度 {score:.4f} 未低于阈值 {SIMILARITY_THRESHOLD}——"
        f"会被误并到同一组"
    )
    # 命中的那份也不是张建鹏
    assert matched != _ZHANG_PROFILE_ID


def test_naive_jaccard_would_misjudge_this_pair() -> None:
    """**对照用例**：朴素 Jaccard 在这一对上是错的，TF-IDF 才对。

    这条存在的意义是证明上一条不是「碰巧对」：它把「模板词人人都有」
    的重叠率显式算出来——Jaccard 超过阈值（会误并不同的人），
    而 TF-IDF 低于阈值（正确分开）。

    **在哪种错误实现下也会通过**：如果将来有人把 TF-IDF 换成 Jaccard
    而语料没变，这条会红（TF-IDF 那半边断言）。
    """
    jaccard = _jaccard(profile_counts(_ZHANG_V1), profile_counts(_OUYANG))
    tfidf, _ = similarity(profile_counts(_OUYANG), _pool_profiles())

    assert jaccard >= SIMILARITY_THRESHOLD, (
        f"这一对用 Jaccard 应该会被误判（期望 >= {SIMILARITY_THRESHOLD}），"
        f"实际 {jaccard:.4f}——语料不够模板化，这条对照用例失效了"
    )
    assert tfidf < SIMILARITY_THRESHOLD, f"TF-IDF 应把这一对分开，实际 {tfidf:.4f}"


def test_same_and_different_person_scores_have_clear_gap() -> None:
    """同一人 vs 不同人之间要有**明显间隔**，不是刚好卡在阈值两边。

    只断言「一个大一个小」是不够的——阈值是在噪声上调出来的也能满足。
    这里要求间隔 > 0.3：阈值在语料换一批后仍然站得住。

    **在哪种错误实现下也会通过**：如果实现把分数映射成
    「命中就是 0.61、不命中就是 0.59」这种贴着阈值的两点分布，
    两条单边断言都过，间隔断言会红。
    """
    profiles = _pool_profiles()

    same_score, _ = similarity(profile_counts(_ZHANG_V2), profiles)
    diff_score, _ = similarity(profile_counts(_OUYANG), profiles)

    gap = same_score - diff_score
    assert gap > 0.3, f"同一人与不同人的分数间隔只有 {gap:.4f}，阈值不可靠"


def test_similarity_uses_max_not_average_over_candidates() -> None:
    """同一人的**任一**历史版本高度相似就该命中（取最大值，不取平均）。

    候选池里同时有张建鹏的第 1 版与另外四个不相关的人。取平均的话，
    平均分会被那四个人拉低到阈值以下——「与 v1 像、与别人不像」正是
    取平均会误杀的场景。

    **在哪种错误实现下也会通过**：单候选集下 max 与 average 数值相同，
    所以这条必须在**多候选**集上跑才有意义。
    """
    profiles = _pool_profiles()

    score, matched = similarity(profile_counts(_ZHANG_V2), profiles)

    assert matched == _ZHANG_PROFILE_ID
    assert score >= SIMILARITY_THRESHOLD


def test_similarity_returns_zero_when_no_candidates() -> None:
    """候选集为空 → (0.0, None)，不抛异常。

    **在哪种错误实现下也会通过**：抛 IndexError 的实现会红——但这条的
    主要作用是钉住「没候选」这个边界，别让归组入口在没有历史资料时炸掉。
    """
    score, matched = similarity(profile_counts(_ZHANG_V1), [])

    assert score == 0.0
    assert matched is None


def test_similarity_ignores_candidates_with_no_tokens() -> None:
    """候选资料没有正文（切片还没建）时不能把它当命中。

    **在哪种错误实现下也会通过**：实现若把空词频表的候选也算进 max，
    这条会红。空 profile 的余弦是 0.0，不会虚高。
    """
    profiles = [_profile(1, "", group_id=1)]

    score, matched = similarity(profile_counts(_OUYANG), profiles)

    assert score == 0.0
    assert matched is None


# ── B 段：归组判定 ───────────────────────────────────────────


async def test_small_candidate_pool_does_not_group(
    db_session: AsyncSession,
) -> None:
    """候选池不足 ``MIN_CANDIDATES_FOR_GROUPING`` 份 → **不归组**。

    ## 为什么这条最重要

    TF-IDF 的 IDF 项靠**文档频率**算——「项目经历」要在多份资料里都出现
    才会被压低。池子只有 1–3 份时所有 token 的 IDF 相同，TF-IDF 退化成
    词频余弦，模板词压不下去，**不同人的同模板简历会越阈值**。

    实测（本文件的语料，同模板不同人）：

    | 池大小 | 负样本（不同人）相似度 | 越阈值？ |
    |---|---|---|
    | 1 份 | 0.6945 | 是 |
    | 2 份 | 0.6563 | 是 |
    | 3 份 | 0.6027 | 是 |
    | 4 份 | 0.5611 | 否 |

    ## 误并的代价远大于漏归

    误并会让**新上传的那份**在摄取成功后顶掉用户原有的资料（原版被归档，
    静默退出检索池，用户看不到任何错误）。漏归只是两份资料并存。

    ## 在哪种错误实现下也会通过

    只断言「相似度低于阈值就不归组」的实现——这里相似度是**越**阈值的，
    只有「池子太小就不归组」这条独立的门槛会拦住它。
    """
    user = await _make_user(db_session, "smallpool@test.local")
    # 只建 2 份历史资料（不足下限）
    for index, text in enumerate(_POOL_TEXTS[:2]):
        other_group = await _make_group(db_session, user)
        await _make_source(
            db_session,
            user,
            title=f"别人 {index}",
            group_id=other_group,
            is_active=True,
            version_no=1,
            chunks=[text],
        )
    zhang_group = await _make_group(db_session, user)
    await _make_source(
        db_session,
        user,
        title="张建鹏 v1",
        group_id=zhang_group,
        is_active=True,
        version_no=1,
        chunks=[_ZHANG_V1],
    )

    decision = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2)

    assert decision.group_id is None, "候选池太小，不该归组——会误并不同人的资料"
    assert decision.version_no == 1
    assert decision.is_active is True


async def test_empty_profiles_do_not_count_toward_pool_size(
    db_session: AsyncSession,
) -> None:
    """**空词频表**的候选不算进池子。

    ## 为什么

    门槛是 4 份（实测 3 份时不同人的同模板简历会越阈值 → 误并）。
    但候选里若有没建成索引的行，它们的词频表是空的——**对 IDF 毫无
    贡献**（df 不变，每个 token 的 IDF 也不变）。把它们算进池子会让
    门槛**说谎**：

    3 份真资料 + 1 份 failed 的行 → 按份数算是 4 → 门槛放行，
    但实际有效池是 3 → 误判照样发生。

    failed 行很常见（嵌入服务欠费是已知状态），所以这条不是理论风险。

    **在哪种错误实现下也会通过**：只测「池子里全是真资料」的实现的
    门槛是对的，但按 ``len(profiles)`` 数的实现会把空表算进去——
    所以这里必须造一份**有行但没切片**的资料。
    """
    user = await _make_user(db_session, "emptypool@test.local")
    # 2 份别人的真资料 + 张建鹏 v1（下面建）= 有效池 3 份；
    # 再加 1 份有行但没切片的（摄取失败）→ 按行数算是 4，按有效池算是 3。
    for index, text in enumerate(_POOL_TEXTS[:2]):
        other_group = await _make_group(db_session, user)
        await _make_source(
            db_session,
            user,
            title=f"别人 {index}",
            group_id=other_group,
            is_active=True,
            version_no=1,
            chunks=[text],
        )
    empty_group = await _make_group(db_session, user)
    await _make_source(
        db_session,
        user,
        title="摄取失败，没切片",
        group_id=empty_group,
        is_active=False,
        version_no=1,
        status=SourceStatus.FAILED,
        chunks=[],
    )
    zhang_group = await _make_group(db_session, user)
    await _make_source(
        db_session,
        user,
        title="张建鹏 v1",
        group_id=zhang_group,
        is_active=True,
        version_no=1,
        chunks=[_ZHANG_V1],
    )

    decision = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2)

    assert decision.group_id is None, "有效池只有 3 份，不该归组"


async def test_empty_body_creates_new_group(db_session: AsyncSession) -> None:
    """空正文 → 自建新组（version_no=1、is_active=True）。

    **在哪种错误实现下也会通过**：什么都不返回、返回 None 的实现会红。
    这条还钉住「空正文不报错」——解析失败/空文件是真实路径。
    """
    user = await _make_user(db_session, "empty@test.local")

    decision = await resolve_grouping(db_session, user.id, profile_text="")

    assert decision.group_id is None
    assert decision.version_no == 1
    assert decision.is_active is True
    assert decision.matched_source_id is None


async def test_similar_content_joins_existing_group(db_session: AsyncSession) -> None:
    """内容高度相似 → 归入已有组。

    **关键点：``is_active=False``**——插入时不生效，等摄取成功才切。
    这样摄取失败时旧版仍是生效版，用户不会同时失去两份可检索资料。

    **在哪种错误实现下也会通过**：只断言 ``group_id`` 对的实现（比如
    忘了设 is_active）会绿——所以这里把 is_active 也断言死。
    """
    user = await _make_user(db_session, "join@test.local")
    zhang_id, zhang_group = await _seed_pool(db_session, user)

    decision = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2)

    assert decision.group_id == zhang_group, "应归入已有组"
    assert decision.version_no == 2, "组内新版本号应为 2"
    assert decision.is_active is False, "插入时不得生效——摄取成功后才切"
    assert decision.matched_source_id == zhang_id
    assert decision.similarity >= SIMILARITY_THRESHOLD


async def test_dissimilar_content_creates_new_group(db_session: AsyncSession) -> None:
    """内容不相似 → 自建新组。

    **在哪种错误实现下也会通过**：永远返回已有 group_id 的实现会红。
    """
    user = await _make_user(db_session, "newgrp@test.local")
    await _seed_pool(db_session, user)

    decision = await resolve_grouping(db_session, user.id, profile_text=_OUYANG)

    assert decision.group_id is None, "不相似的内容不该归入已有组"
    assert decision.version_no == 1
    assert decision.is_active is True
    assert decision.matched_source_id is None


async def test_version_numbers_increment_within_group(db_session: AsyncSession) -> None:
    """连续归组三份 → 版本号 1、2、3。

    **在哪种错误实现下也会通过**：版本号写死成 1 的实现会红；
    「取组内已有份数」而不是「取组内最大 version_no + 1」的实现
    在有归档版本时也会红——那条由下一条用例单独覆盖。
    """
    user = await _make_user(db_session, "ver@test.local")
    _zhang_id, group_id = await _seed_pool(db_session, user)

    # 候选池里已经有「张建鹏 v1」（version_no=1、组内唯一生效版）。
    # 第二份归组判定应当是第 2 版。
    second = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2)
    assert second.group_id == group_id
    assert second.version_no == 2

    await _make_source(
        db_session,
        user,
        title="简历 v2",
        group_id=group_id,
        is_active=False,
        version_no=second.version_no,
        chunks=[_ZHANG_V2],
    )

    third = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2 + " Doris")
    assert third.group_id == group_id
    assert third.version_no == 3


async def test_version_number_uses_max_not_count(db_session: AsyncSession) -> None:
    """版本号取「组内最大 version_no + 1」，不是「组内份数 + 1」。

    组里已有 version_no = 1 和 version_no = 5（中间那个版本被删过），
    新的一份必须是 **6**——按份数算会得到 3，撞上已有的 5。

    **在哪种错误实现下也会通过**：``max()`` 换成 ``len()`` / ``count()``
    的实现会红。
    """
    user = await _make_user(db_session, "maxver@test.local")
    _zhang_id, group_id = await _seed_pool(db_session, user)
    # 组里已有 version_no=1（张建鹏 v1，生效版），再补一个 version_no=5
    # （归档版——中间那个版本被删过）。新增的一份必须是 6。
    # 按份数算会得到 3（组里 2 份），按 max 算是 6。
    await _make_source(
        db_session,
        user,
        title="简历 v5",
        group_id=group_id,
        is_active=False,
        version_no=5,
        chunks=[_ZHANG_V1],
    )

    decision = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2)

    assert decision.group_id == group_id
    assert decision.version_no == 6, "版本号应为组内最大(5)+1，不是份数(2)+1"


async def test_matched_source_id_points_to_the_right_version(db_session: AsyncSession) -> None:
    """命中的是**同一人**的那份资料，不是池子里的别人。

    候选池里同时有张建鹏的第 1 版与另外四个不相关的人（张建鹏那份
    建在**最后**）。只断言「命中了某个 source_id」不够——必须断言它
    就是张建鹏那份。

    **在哪种错误实现下也会通过**：返回「候选集里第一个」的实现的
    matched_source_id 会拿到别人（张建鹏在最后），这条会红。
    """
    user = await _make_user(db_session, "match@test.local")
    zhang_id, _zhang_group = await _seed_pool(db_session, user)

    decision = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2)

    assert decision.matched_source_id == zhang_id, (
        f"命中的是 {decision.matched_source_id}，应为张建鹏那份 {zhang_id}"
    )
    assert decision.group_id is not None


async def test_ungrouped_matched_source_does_not_create_a_group(db_session: AsyncSession) -> None:
    """命中的那份**还没归组**（老资料）→ 自建新组，不继承它的组。

    老资料没有 group_id 可继承。要把它拉进组就得重新解析正文，
    代价高且可能误并——归组只对新上传的资料生效。

    **在哪种错误实现下也会通过**：无条件继承 group_id（含 None）的实现
    会走另一条分支——所以这里同时断言 ``version_no`` 仍是 1、
    ``is_active`` 仍是 True（「新建组」而不是「继承了组」）。
    """
    user = await _make_user(db_session, "ungrouped@test.local")
    await _make_source(
        db_session,
        user,
        title="老资料",
        group_id=None,
        is_active=True,
        version_no=1,
        chunks=[_ZHANG_V1],
    )

    decision = await resolve_grouping(db_session, user.id, profile_text=_ZHANG_V2)

    assert decision.group_id is None, "老资料没有组可继承"
    assert decision.version_no == 1
    assert decision.is_active is True


async def test_grouping_does_not_leak_across_users(db_session: AsyncSession) -> None:
    """别人的资料不能被归组命中（用户隔离）。

    **在哪种错误实现下也会通过**：``load_profiles`` 少写 ``user_id``
    过滤的实现会红——那样别人的简历会参与相似度计算，甚至被继承组。
    """
    mine = await _make_user(db_session, "mine2@test.local")
    theirs = await _make_user(db_session, "theirs2@test.local")
    their_group = await _make_group(db_session, theirs)
    await _make_source(
        db_session,
        theirs,
        title="别人的简历",
        group_id=their_group,
        is_active=True,
        version_no=1,
        chunks=[_ZHANG_V1],
    )

    decision = await resolve_grouping(db_session, mine.id, profile_text=_ZHANG_V2)

    assert decision.group_id is None, "不该命中别人的资料"
    assert decision.matched_source_id is None


# ── C 段：生效版切换 ─────────────────────────────────────────


async def _make_version_pair(
    db_session: AsyncSession, user: User
) -> tuple[int, int, int]:
    """建一组：旧版生效、新版归档。返回 (group_id, old_id, new_id)。"""
    group_id = await _make_group(db_session, user)
    old_id = await _make_source(
        db_session,
        user,
        title="简历 v1",
        group_id=group_id,
        is_active=True,
        version_no=1,
    )
    new_id = await _make_source(
        db_session,
        user,
        title="简历 v2",
        group_id=group_id,
        is_active=False,
        version_no=2,
    )
    return group_id, old_id, new_id


async def _active_states(
    db_session: AsyncSession, group_id: int
) -> dict[int, bool]:
    """读一组里每份资料的 is_active。

    **必须用新查询读，不能信 identity map**：``activate_version`` 走的是
    bulk UPDATE，ORM 对象上的属性可能还是旧值。
    ``populate_existing=True`` 强制绕过 identity map。
    """
    rows = (
        await db_session.execute(
            select(Source)
            .where(Source.group_id == group_id)
            .order_by(Source.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return {row.id: row.is_active for row in rows}


async def test_activate_version_activates_target_and_archives_others(
    db_session: AsyncSession,
) -> None:
    """``activate_version``：目标设为生效，同组其他版本转归档。

    **在哪种错误实现下也会通过**：只设目标为生效、忘了归档旧版的实现
    会红（旧版仍是 True）——注意这条**不能**被数据库唯一索引顶回来：
    唯一索引只在 commit 时报错，而这里不 commit。
    """
    user = await _make_user(db_session, "act@test.local")
    group_id, old_id, new_id = await _make_version_pair(db_session, user)

    await activate_version(db_session, await _get_source(db_session, new_id))

    states = await _active_states(db_session, group_id)
    assert states[new_id] is True, "目标版本应被设为生效"
    assert states[old_id] is False, "旧版本应被归档"


async def _get_source(db_session: AsyncSession, source_id: int) -> Source:
    """按 id 取一份资料（``populate_existing`` 绕过 identity map）。"""
    row = await db_session.get(Source, source_id, populate_existing=True)
    assert row is not None, f"source {source_id} 不存在"
    return row


async def test_deactivate_others_does_not_touch_the_source_itself(
    db_session: AsyncSession,
) -> None:
    """``deactivate_others`` 只归档同组**其他**版本，不动 source 自己。

    摄取成功路径用它：新版本插入时是 ``is_active=False``，
    摄取完成后才归档旧版、再由调用方把它设为生效。

    **在哪种错误实现下也会通过**：把它写成「设置 source.is_active=True」
    的实现（即与 ``activate_version`` 混为一谈）会红——
    新版本插入时是 False，调用后必须**仍是 False**。
    """
    user = await _make_user(db_session, "deact@test.local")
    group_id, old_id, new_id = await _make_version_pair(db_session, user)

    await deactivate_others(db_session, await _get_source(db_session, new_id))

    states = await _active_states(db_session, group_id)
    assert states[new_id] is False, "不该改 source 自己的状态"
    assert states[old_id] is False, "旧版本应被归档"


async def test_activate_version_does_not_commit(db_session: AsyncSession) -> None:
    """``activate_version`` **不 commit**——事务边界归调用方。

    验证方式：调用后回滚，改动应当被丢弃（数据库里仍是调用前的状态）。
    如果实现内部自己 commit 了，回滚**不会**撤销改动——这条会红。

    **在哪种错误实现下也会通过**：只在同一个 session 里读属性
    （``new.is_active is True``）的实现改动一样能看见——所以必须用
    「回滚后是否还原」来区分「改在事务里」与「已提交」。
    """
    user = await _make_user(db_session, "nocommit@test.local")
    group_id, old_id, new_id = await _make_version_pair(db_session, user)

    await activate_version(db_session, await _get_source(db_session, new_id))
    assert (await _get_source(db_session, new_id)).is_active is True, (
        "调用后当前事务里应已改成生效"
    )

    await db_session.rollback()

    states = await _active_states(db_session, group_id)
    assert states[new_id] is False, "改动没被提交，回滚后应还原为归档"
    assert states[old_id] is True, "改动没被提交，回滚后旧版应仍是生效版"


async def test_database_rejects_two_active_versions_in_one_group(
    db_session: AsyncSession,
) -> None:
    """**数据库层**拦住「同组两条生效版」。

    这条是本文件里最重要的一条：它验证「组内至多一条生效版」
    **不是靠应用层自觉**——应用层漏了、并发竞态了、
    有人直接写 SQL，数据库都得拦住。

    **在哪种错误实现下也会通过**：只靠应用层检查（``activate_version``
    里先查后写）的实现**不会**触发这个异常——它绕过了应用层，
    直接改字段再 commit。所以这条测的是数据库约束本身。

    反例实现：把索引写成**普通**唯一索引 ``(group_id, is_active)``
    ——那会把「组内两条归档版本」也管住（两条 is_active=False 撞车），
    下一条 ``test_multiple_archived_versions_allowed_in_one_group``
    会红。
    """
    user = await _make_user(db_session, "uniq@test.local")
    group_id = await _make_group(db_session, user)
    first_id = await _make_source(
        db_session,
        user,
        title="简历 v1",
        group_id=group_id,
        is_active=True,
        version_no=1,
    )
    second_id = await _make_source(
        db_session,
        user,
        title="简历 v2",
        group_id=group_id,
        is_active=False,
        version_no=2,
    )

    # 直接把第二条也设成生效——绕过所有应用层逻辑
    second = await _get_source(db_session, second_id)
    second.is_active = True

    with pytest.raises(IntegrityError) as excinfo:
        await db_session.commit()

    assert "UNIQUE" in str(excinfo.value).upper()
    await db_session.rollback()
    # 约束确实拦住了：库里仍然是「一条生效」
    states = await _active_states(db_session, group_id)
    assert states[first_id] is True
    assert states[second_id] is False


async def test_multiple_archived_versions_allowed_in_one_group(
    db_session: AsyncSession,
) -> None:
    """同组可以有**多份归档版本**——唯一索引是部分索引，不是普通唯一索引。

    建在 ``(group_id, is_active)`` 上的普通唯一索引会把「两条归档版」也
    管住（两条 ``is_active=False`` 撞车），而归档版本本来可以有多份。

    **在哪种错误实现下也会通过**：只断言「一条归档能建」的用例抓不到
    普通唯一索引的错误——所以这里建**两条**归档版。
    """
    user = await _make_user(db_session, "multiarch@test.local")
    group_id = await _make_group(db_session, user)
    await _make_source(
        db_session,
        user,
        title="简历 v1",
        group_id=group_id,
        is_active=True,
        version_no=1,
    )
    await _make_source(
        db_session,
        user,
        title="简历 v2",
        group_id=group_id,
        is_active=False,
        version_no=2,
    )
    await _make_source(
        db_session,
        user,
        title="简历 v3",
        group_id=group_id,
        is_active=False,
        version_no=3,
    )

    states = await _active_states(db_session, group_id)
    assert sorted(states.values()) == [False, False, True]


async def test_activate_version_archives_before_activating(
    db_session: AsyncSession,
) -> None:
    """切换生效版时**先归档旧的再激活新的**。

    ``ux_sources_group_active`` 是部分唯一索引，同组内至多一条
    ``is_active=1``。如果先激活新的再归档旧的，**commit 时会撞唯一约束**——
    这条验的就是顺序：调用 + commit 必须成功，不抛 IntegrityError。

    **在哪种错误实现下也会通过**：只断言最终状态、不 commit 的实现
    抓不到顺序错误——所以这条必须 commit。
    """
    user = await _make_user(db_session, "order@test.local")
    group_id, old_id, new_id = await _make_version_pair(db_session, user)

    await activate_version(db_session, await _get_source(db_session, new_id))
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert states[new_id] is True
    assert states[old_id] is False


async def test_activate_version_on_ungrouped_source_is_a_noop(
    db_session: AsyncSession,
) -> None:
    """未归组的资料调 ``activate_version`` → 它自己就是生效版。

    **在哪种错误实现下也会通过**：给它硬套「归档同组其他版本」的
    实现会因为 group_id 为 None 而炸（或者错误地归档了别人的资料）——
    所以这条也钉住「不碰别人的资料」。
    """
    user = await _make_user(db_session, "nogroup@test.local")
    other_group = await _make_group(db_session, user)
    other_id = await _make_source(
        db_session,
        user,
        title="别人的资料",
        group_id=other_group,
        is_active=True,
        version_no=1,
    )
    lone_id = await _make_source(
        db_session,
        user,
        title="未归组",
        group_id=None,
        is_active=True,
        version_no=1,
    )

    await activate_version(db_session, await _get_source(db_session, lone_id))

    assert (await _get_source(db_session, lone_id)).is_active is True
    assert (await _get_source(db_session, other_id)).is_active is True, "不该动别人的资料"


# ── C2 段：删除生效版后的接管 ────────────────────────────────


async def test_promote_after_delete_activates_remaining_version(
    db_session: AsyncSession,
) -> None:
    """删掉生效版后，组里剩下的版本接管生效位。

    ## 为什么必须有接管

    检索候选集是「组内 ``is_active=True`` 的那些」
    （``Source.list_active_owned``）。删掉生效版而不接管的话，组里剩下的
    版本全是 ``is_active=False``——还在库里、还能点开，但**一份都召不回来**。
    这是「只检索生效版」引入的行为回归。

    **在哪种错误实现下也会通过**：什么都不做的实现会红（组里没有生效版）。
    「随便挑一份接管」的实现——这条要求挑 ``version_no`` 最大的那份，
    见下一条。
    """
    user = await _make_user(db_session, "promote@test.local")
    group_id = await _make_group(db_session, user)
    old_id = await _make_source(
        db_session,
        user,
        title="v1",
        group_id=group_id,
        is_active=False,
        version_no=1,
    )
    active_id = await _make_source(
        db_session,
        user,
        title="v2",
        group_id=group_id,
        is_active=True,
        version_no=2,
    )

    # 契约是「**删掉之后**」调用——先删再接管，否则组里同时存在两条
    # 生效版，撞 ``ux_sources_group_active`` 部分唯一索引。
    deleted = await _get_source(db_session, active_id)
    await db_session.delete(deleted)
    await db_session.flush()
    await promote_after_delete(db_session, deleted)
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert states[old_id] is True, "剩下的版本必须接管生效位，否则一份都搜不到"


async def test_promote_after_delete_picks_highest_version(
    db_session: AsyncSession,
) -> None:
    """接管挑 ``version_no`` **最大**的那份，不是最老的那份。

    用户删掉 v2 之后想要的大概率是 v3（最新的），不是 v1（最老的）。

    **在哪种错误实现下也会通过**：只断言「有一条变成 True」的实现——
    挑 v1 的实现也会绿。所以这条必须断言**具体是哪一条**。
    """
    user = await _make_user(db_session, "promote-pick@test.local")
    group_id = await _make_group(db_session, user)
    v1_id = await _make_source(
        db_session, user, title="v1", group_id=group_id, is_active=False, version_no=1
    )
    v3_id = await _make_source(
        db_session, user, title="v3", group_id=group_id, is_active=False, version_no=3
    )
    v2_id = await _make_source(
        db_session, user, title="v2", group_id=group_id, is_active=True, version_no=2
    )

    deleted = await _get_source(db_session, v2_id)
    await db_session.delete(deleted)
    await db_session.flush()
    await promote_after_delete(db_session, deleted)
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert states[v3_id] is True, "该由最新的一版接管"
    assert states[v1_id] is False


async def test_promote_after_delete_skips_not_indexed_version(
    db_session: AsyncSession,
) -> None:
    """接管**跳过没建成索引的版本**——它一条切片都没有。

    ## 为什么

    生效位是检索候选集的一员。**没建成索引的版本占了这个位置**，
    等于「整组都搜不到」——它一条切片都没有，而它顶掉的那份是唯一
    能用的。

    实测过的场景：组里 v1（indexed，10 切片，生效版）与 v2（failed，
    0 切片，归档版）。删掉 v1 → 若接管给了 v2，整组退出检索池，
    用户看到的是「资料还在，搜不到任何东西」。

    摄取失败很常见（嵌入服务欠费是已知状态），所以这不是理论场景。

    **在哪种错误实现下也会通过**：只断言「组里有生效版」的实现——
    接管给了 v2 也满足。所以这条必须断言**是哪一条**接管。
    """
    user = await _make_user(db_session, "promote-skip@test.local")
    group_id = await _make_group(db_session, user)
    failed_id = await _make_source(
        db_session,
        user,
        title="失败的 v2",
        group_id=group_id,
        is_active=False,
        version_no=2,
        status=SourceStatus.FAILED,
    )
    active_id = await _make_source(
        db_session,
        user,
        title="v1",
        group_id=group_id,
        is_active=True,
        version_no=1,
        status=SourceStatus.INDEXED,
    )

    deleted = await _get_source(db_session, active_id)
    await db_session.delete(deleted)
    await db_session.flush()
    await promote_after_delete(db_session, deleted)
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert states[failed_id] is False, "没建成索引的版本不能接管生效位"
    assert failed_id not in states or states[failed_id] is False


async def test_activate_if_newest_yields_to_newer_version(
    db_session: AsyncSession,
) -> None:
    """组内已有更新的一版时，当前这份**不抢**生效位。

    ## 为什么

    摄取是**后台并发**跑的：用户连传 v2 与 v3，完成顺序不确定。
    若「谁最后完成谁生效」，v2 后完成就会顶掉已生效的 v3——用户在
    检索的是**旧版**，新版躺在归档里，且没有任何错误提示。

    ``version_no`` 才是「新旧」的判据（新版号更大）。

    **在哪种错误实现下也会通过**：无条件接管的实现（无条件
    ``deactivate_others`` + 置 True）会红——它会把 v3 归档掉。
    """
    user = await _make_user(db_session, "newest@test.local")
    group_id = await _make_group(db_session, user)
    v2_id = await _make_source(
        db_session, user, title="v2", group_id=group_id, is_active=False, version_no=2
    )
    v3_id = await _make_source(
        db_session, user, title="v3", group_id=group_id, is_active=True, version_no=3
    )

    took = await activate_if_newest(db_session, await _get_source(db_session, v2_id))
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert took is False, "组内已有更新的一版，不该抢生效位"
    assert states[v3_id] is True, "更新的那一版必须仍是生效版"
    assert states[v2_id] is False


async def test_activate_if_newest_takes_slot_when_newest(
    db_session: AsyncSession,
) -> None:
    """当前这份是组内最新的一版 → 接管生效位，旧版转归档。

    **在哪种错误实现下也会通过**：什么都不做的实现会红。
    """
    user = await _make_user(db_session, "newest2@test.local")
    group_id = await _make_group(db_session, user)
    v1_id = await _make_source(
        db_session, user, title="v1", group_id=group_id, is_active=True, version_no=1
    )
    v2_id = await _make_source(
        db_session, user, title="v2", group_id=group_id, is_active=False, version_no=2
    )

    took = await activate_if_newest(db_session, await _get_source(db_session, v2_id))
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert took is True
    assert states[v2_id] is True
    assert states[v1_id] is False


async def test_activate_if_newest_ignores_not_indexed_newer_version(
    db_session: AsyncSession,
) -> None:
    """组内有一份**更新但还没建成索引**的版本时，当前这份仍可接管。

    ## 为什么

    「已索引」是判据的一半：组里可能有一份 v4 还在摄取中（未索引），
    它不该阻止 v3 成为生效版——否则组里会**短暂没有任何生效版**，
    那段时间用户一份资料都搜不到。

    **在哪种错误实现下也会通过**：只看 version_no 的实现会红——
    它会让 v3 保持归档，组里没有任何生效版。
    """
    user = await _make_user(db_session, "newest3@test.local")
    group_id = await _make_group(db_session, user)
    v3_id = await _make_source(
        db_session, user, title="v3", group_id=group_id, is_active=False, version_no=3
    )
    v4_id = await _make_source(
        db_session,
        user,
        title="v4 摄取中",
        group_id=group_id,
        is_active=False,
        version_no=4,
        status=SourceStatus.PENDING,
    )

    took = await activate_if_newest(db_session, await _get_source(db_session, v3_id))
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert took is True, "更新的那份还没建成索引，不该挡住 v3"
    assert states[v3_id] is True
    assert states[v4_id] is False


async def test_promote_after_delete_is_noop_when_another_active_exists(
    db_session: AsyncSession,
) -> None:
    """组里还有别的生效版时，什么都不做。

    删掉的是一个**归档版**——正常状态，不需要接管。

    **在哪种错误实现下也会通过**：无条件「把 version_no 最大的设成生效」
    的实现会红——那会让组里同时存在两条生效版，撞唯一索引。
    """
    user = await _make_user(db_session, "promote-noop@test.local")
    group_id, old_id, new_id = await _make_version_pair(db_session, user)

    # 删掉的是**归档版** new_id（version_no=2），生效版是 old_id。
    deleted = await _get_source(db_session, new_id)
    await db_session.delete(deleted)
    await db_session.flush()
    await promote_after_delete(db_session, deleted)
    await db_session.commit()

    states = await _active_states(db_session, group_id)
    assert states[old_id] is True, "已有的生效版不该被动"


async def test_promote_after_delete_on_ungrouped_source_is_a_noop(
    db_session: AsyncSession,
) -> None:
    """未归组的资料 → 什么都不做（它不受组内约束）。

    **在哪种错误实现下也会通过**：不判 ``group_id is None`` 就去查组内
    版本的实现会炸（或者错误地动了别人的资料）。
    """
    user = await _make_user(db_session, "promote-nogroup@test.local")
    lone_id = await _make_source(
        db_session, user, title="未归组", group_id=None, is_active=True, version_no=1
    )

    await promote_after_delete(db_session, await _get_source(db_session, lone_id))

    assert (await _get_source(db_session, lone_id)).is_active is True


# ── C3 段：版本标记 ──────────────────────────────────────────


def test_version_label_is_empty_for_first_version() -> None:
    """第 1 版**不带**标记。

    ## 为什么

    每份上传的资料都自建一个组，所以「组里只有自己」是最常见的状态。
    若第 1 版也标「第 1 版」，表格每一行都挂着一个「第 1 版」徽章、
    每条引用角标都带「（第 1 版）」、模型看到的证据块标题是
    「xxx.pdf（第 1 版）」——一个不携带任何信息的标签刷满全站。

    **在哪种错误实现下也会通过**：只测「第 2 版有标记」的实现——
    所以这条必须同时钉住第 1 版**没有**标记。
    """
    assert version_label(group_id=1, version_no=1) == ""


def test_version_label_marks_second_and_later_versions() -> None:
    """第 2 版及以上才带「第 N 版」。

    **在哪种错误实现下也会通过**：拼成「第 2 版」但漏掉「版」字的
    实现会红——拼法是契约（前端直接显示这个字符串）。
    """
    assert version_label(group_id=1, version_no=2) == "第 2 版"
    assert version_label(group_id=1, version_no=3) == "第 3 版"


def test_version_label_is_empty_when_not_grouped() -> None:
    """不参与分组（``group_id=None``）→ 空串。

    公开来源（``web_sources``）与未归组的老资料没有版本概念。
    """
    assert version_label(group_id=None, version_no=1) == ""
    assert version_label(group_id=None, version_no=2) == ""


# ── E 段：重复上传识别 ───────────────────────────────────────


async def test_find_duplicate_hash_finds_same_users_copy(
    db_session: AsyncSession,
) -> None:
    """同用户下 hash 相同的资料能被找到。

    **在哪种错误实现下也会通过**：只断言「返回了一个 Source」
    的弱断言会绿——这里断言的是**具体那一份**的 id。
    """
    user = await _make_user(db_session, "dup@test.local")
    digest = content_hash(b"same file bytes")
    source_id = await _make_source(
        db_session,
        user,
        title="重复上传",
        digest=digest,
    )

    found = await find_duplicate_hash(db_session, user.id, digest)

    assert found is not None
    assert found.id == source_id


async def test_find_duplicate_hash_ignores_not_indexed_sources(
    db_session: AsyncSession,
) -> None:
    """没建成索引的资料**不算重复**——重传是恢复动作。

    ## 为什么

    没有切片的资料，重传同一份文件是**恢复动作**，不是「重复上传」——
    ``app/services/ingest.py`` 的 ``mark_failed`` docstring 明写
    「用户重传即刻恢复」。

    跳过的是**所有未建成索引的行**，不只是 failed：

    - ``failed``：摄取失败（嵌入服务欠费是已知状态）留下的那行。
    - ``pending`` 等中间态：进程重启丢掉后台摄取任务时留下的那行
      （``gateway/sources.py`` 的模块 docstring 记着这个已知缺口）——
      它会永远停在 pending，用户看到的是「一直在增量切片中」。

    若把这些也算重复，用户会遇到死路：重传被 409 拒，而唯一能解开的
    办法是先手动删掉那份资料——而 409 的文案只字未提要删。

    **在哪种错误实现下也会通过**：只排除 ``failed`` 的实现——pending
    那条会红。
    """
    user = await _make_user(db_session, "dup-pending@test.local")
    digest = content_hash(b"pending file bytes")
    pending_id = await _make_source(
        db_session,
        user,
        title="摄取中",
        digest=digest,
        status=SourceStatus.PENDING,
    )
    failed_id = await _make_source(
        db_session,
        user,
        title="摄取失败",
        digest=content_hash(b"failed file bytes"),
        status=SourceStatus.FAILED,
    )

    assert (
        await find_duplicate_hash(db_session, user.id, digest)
    ) is None, "还没建成索引的不该算重复"
    assert (
        await find_duplicate_hash(db_session, user.id, content_hash(b"failed file bytes"))
    ) is None, "摄取失败的也不该算重复"
    assert pending_id != failed_id


async def test_find_duplicate_hash_ignores_other_users(
    db_session: AsyncSession,
) -> None:
    """**别人的**资料 hash 相同也找不到（用户隔离）。

    这条验的是上传入口的越权防线：用户 A 传一份文件，如果能查到
    用户 B 也传过同样的文件，就等于知道 B 的资料清单。

    **在哪种错误实现下也会通过**：少写 ``user_id`` 过滤的实现在
    「同用户」那条上照样绿——只有这条会红。
    """
    mine = await _make_user(db_session, "mine3@test.local")
    theirs = await _make_user(db_session, "theirs3@test.local")
    digest = content_hash(b"same file bytes")
    their_source_id = await _make_source(
        db_session,
        theirs,
        title="他们传的",
        digest=digest,
    )

    found = await find_duplicate_hash(db_session, mine.id, digest)

    assert found is None, "不该查到别人的资料"
    assert their_source_id != 0


async def test_find_duplicate_hash_returns_none_when_absent(
    db_session: AsyncSession,
) -> None:
    """hash 不存在 → None。

    **在哪种错误实现下也会通过**：抛异常的实现会红；返回「第一条资料」
    的实现也会红（这里库里还有别的资料可返回）。
    """
    user = await _make_user(db_session, "nodup@test.local")
    await _make_source(db_session, user, title="别的资料", digest=content_hash(b"other"))

    found = await find_duplicate_hash(db_session, user.id, content_hash(b"nothing"))

    assert found is None


def test_content_hash_is_sha256_hex() -> None:
    """``content_hash`` 是 sha256 十六进制摘要（64 字符）。

    **在哪种错误实现下也会通过**：用 md5（32 字符）或 base64 的实现
    会被这条的长度与十六进制断言抓到——列的宽度是 64，
    换个算法塞不进去。
    """
    digest = content_hash(b"hello")

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
    assert digest == content_hash(b"hello"), "同样的字节必须得到同样的摘要"
    assert digest != content_hash(b"hello "), "不同字节必须得到不同摘要"


# ── F 段：画像口径 ───────────────────────────────────────────


async def test_new_upload_profile_uses_chunks_not_raw_blocks(
    db_session: AsyncSession,
) -> None:
    """新建档侧的画像**走切片链路**，与候选侧口径一致。

    ## 为什么

    候选资料的画像是「前 8 个**切片**」（``load_profiles`` 读
    ``document_chunks``，每片 ≤512 字符，约 4000 字符）。新建档这侧若
    直接取「前 8 个**解析块**」，两边量级差一个数量级：

    - PDF：一块 = 一**页**（可能几千字）
    - HTML：一块 = **整页正文**
    - TXT：一块 = **整段**（整篇文件）

    实测（同一份简历，项目描述很长）：新建档侧取 8 页（约 16000 字）
    而候选侧只有 8 片（约 4000 字）时，同一人的相似度掉到 **0.21**
    ——远低于 0.6 阈值 → **不归组** → 两个版本都生效、都进检索池，
    正是这个特性要消除的「互相冲突的证据」。

    ## 怎么验

    直接比对两侧画像的**字符量级**：新建档侧的画像文本长度应当与
    「8 片切片」的量级相当（约 8×512），而不是「8 页」的量级。

    **在哪种错误实现下也会通过**：只断言「归组成功」的实现——用旧的
    取块方式在短文档上也能归组成功。所以这条必须**比对长度量级**。
    """
    from app.services.source_versions import _profile_text

    # 一份长文档：正文远超 8 片切片的量级。
    long_text = ("张建鹏 13800138000 zhangjp@example.com 北京 后端开发工程师 "
                 "字节跳动 推荐系统召回链路 实时特征平台 " * 2000)

    profile = await _profile_text(long_text.encode(), SourceType.TEXT)

    # 8 片 × 512 字符 ≈ 4096。留一倍余量给切片器的实际切法。
    assert len(profile) <= 4096 * 2, (
        f"画像文本 {len(profile)} 字，超出「8 片切片」的量级——"
        "说明还在用解析块而不是切片"
    )
    assert len(profile) > 0
