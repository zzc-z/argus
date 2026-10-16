"""Citation Builder：把检索结果变成模型可引用的证据块 + 前端可点的引用表。

对应 prd/rag-pipeline.md §9。输入是 :func:`app.services.retriever.retrieve`
返回的 ``Retrieved`` 列表，输出两样东西：

1. :class:`ReferenceTable` —— 编号分配器，编号 → chunk_id/source_id/page
   的映射，前端点 ``[n]`` 靠它跳回原文
2. :func:`render_evidence` / :func:`citation_rules` —— 喂进 prompt 的
   编号证据块与写作规则，让模型用 ``[n]`` 引用

## 为什么编号必须由这里统一生成

让模型自己编号必然出错：同一段素材它可能在第一处写 ``[1]``、第二处写
``[3]``（第二段其实是第 3 块），也可能漏引。更糟的是它会给没给过的素材
编一个 ``[9]``。所以编号由本模块按检索排名分配，写进 prompt 时逐块标注
「这是第 n 块」，模型只是**引用**既有编号，不分配。

引用号从 1 起：0 容易被「``[0]`` = 未标注」的直觉误读，也与
rag-pipeline §9.1 的示例不一致。

## 引用表里为什么不放正文

前端要展示原文时自己调 ``GET /sources/{id}/chunks``。这里只放定位信息
（哪份资料、第几片、第几页）。放全文会让 SSE 帧膨胀——一次 8 条引用 ×
500 字 ≈ 4KB，仅为了跳转让前端多收一遍全文。
``excerpt`` 是例外：120 字前缀，供角标 tooltip 直接显示，省一次请求。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.retriever import Retrieved

# 喂给模型的单块正文上限。切片按 512 字切，但个别解析器吐的长句可能
# 超长，不截会让单块吃掉大量上下文预算。
CHUNK_CONTENT_CHARS = 800

# 引用表里 excerpt 的长度。
EXCERPT_CHARS = 120

# 引用表最多编多少个号。
#
# 不封顶会怎样：MAX_TURNS=6 × LOCAL_SEARCH_TOP_K=12 → 最多约 72 条。
# 每条往 ``reference`` 帧与 ``citation_rules`` 里各占一份，而
# ``citation_rules`` 的上界是累积总数——模型会被告知「编号 [1] 到 [72]」，
# 那个跨度它根本记不住，反而更容易编错号。
#
# 为什么是 10：一次研究能真正引用上的素材本来就有限，10 条足够覆盖
# 「一个主题的多个侧面」。再多主要是在稀释注意力。
MAX_REFERENCES = 10


@dataclass(frozen=True, slots=True)
class Reference:
    """一条引用。``n`` 与 prompt 里的 ``[n]`` 一一对应。

    ## 字段名对齐前端既有契约

    ``apps/web/app/(dashboard)/explore/mock.ts`` 里已有 ``Citation``：

        interface Citation { id: number; sourceTitle: string; url: string; date: string }

    前端点角标直接吃这个形状（``InspectorDrawer.buildCitationPayload``）。
    所以这里**沿用它的字段名**而不是另立一套——多一列就得在前端多写一层
    转换，而两边字段名不一致时，那个转换迟早会漏。

    ``chunk_id`` / ``page`` / ``recall`` 是后端额外的：前端点开后调
    ``GET /sources/{id}/chunks`` 要用 ``chunk_id`` 定位，``page`` 用来决定
    显示「第 N 页」。当前前端还没用到，不算破坏契约——多字段不影响
    它按名字取已有那几个。
    """

    n: int
    """引用编号。前端 ``Citation.id``。"""
    chunk_id: int
    source_id: int
    chunk_index: int
    page: int | None
    title: str
    excerpt: str
    recall: str
    """召回来源："向量+BM25" / "向量" / "BM25"。前端用它标注引用强度。"""

    def to_citation(self, *, url: str = "", date: str = "") -> dict[str, object]:
        """转成前端 ``Citation`` 形状的字典，随 ``reference`` 事件下发。

        ## 为什么 ``url`` / ``date`` 是参数而不是从 ``Source`` 取

        前端 ``Citation`` 把这两个字段声明为必填，但本地资料是**上传的文件**
        ——它没有 URL 也没有发表日期。``Source`` 上只有 ``created_at``
        （用户什么时候传的），拿它当发表日期是骗用户。

        所以默认给空串：前端只用来显示（``buildCitationPayload`` 渲染成
        ``canonical_url`` / ``publication_date``），空串不崩，而编一个日期
        会误导人判断资料时效。

        网页资料（走 URL 建源那条路）可以传真值——调用方从
        ``Source.url`` 取即可。

        ## 为什么同时给两套命名

        ``n``/``title`` 是后端内部与 prompt 的约定，``id``/``sourceTitle``
        是前端契约。两套都发是为了让后端日志与前端调试时看到的字段名一致，
        排查「角标指错」这类问题时能对得上号。
        """
        return {
            "n": self.n,
            "id": self.n,
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "chunk_index": self.chunk_index,
            "page": self.page,
            "title": self.title,
            "sourceTitle": self.title,
            "url": url,
            "date": date,
            "excerpt": self.excerpt,
            "recall": self.recall,
        }


class ReferenceTable:
    """一次研究请求内的编号分配器，跨多次 ``local_search`` 调用保持稳定。

    ## 为什么编号必须全局稳定

    模型完全可能连续调两次 ``local_search``（「先查财务数据，再查产品
    规格」）。如果每次调用都从 1 开始编，模型在正文第一段写的 ``[1]``
    指向财务数据、在第三段写的 ``[1]`` 却指向产品规格——同一份引用表
    对应两个完全不同的 chunk。用户点角标跳到的原文是错的，而且**没有任何
    报错**：正文里的 ``[1]`` 一直是合法的字符串。

    所以编号器按 chunk_id 记账：已发过号的复用，新切片才取下一个号。
    去重也顺带解决了——同一个切片被两轮检索召回时不会占两个号。

    这个类**不是线程安全的**，但也不需要安全：一次 SSE 流内是单协程顺序
    执行的，且每个请求有自己的实例（由 agent 循环持有，不放模块级全局——
    并发请求会互相串号）。
    """

    def __init__(self) -> None:
        # chunk_id → 引用号。dict 而非 set：要反查编号。
        self._numbers: dict[int, int] = {}
        # 引用号 → 引用。all 靠它按编号升序输出。
        self._references: dict[int, Reference] = {}
        self._dropped = 0

    def register(self, results: Sequence[Retrieved]) -> list[tuple[Reference, Retrieved]]:
        """给一批检索结果分配编号，返回「(引用, 检索结果)」对。

        返回对而不是光引用，是因为 :func:`render_evidence` 还要拿
        ``Retrieved`` 里的完整正文（``Reference.excerpt`` 只截 120 字）。
        光返回引用的话，重复切片会让引用列表变短，与结果列表错位。

        已编过号的切片复用原号，不新增条目——所以返回长度可能小于
        ``len(results)``。

        ## 满表之后的行为

        到 ``MAX_REFERENCES`` 为止不再发新号，超出的切片**不进证据块**。
        静默丢弃是有意的：表满说明这次研究已经取了足够多的素材，再塞
        只会稀释模型注意力。但要让模型知道「还有更多没给」——否则它会
        以为资料就这些，在结论里下「没有更多数据」的判断。
        """
        pairs: list[tuple[Reference, Retrieved]] = []
        dropped = 0
        for hit in results:
            if self._numbers.get(hit.chunk.id) is None and self._is_full():
                dropped += 1
                continue
            pairs.append((self._lookup(hit), hit))
        if dropped:
            self._dropped += dropped
        return pairs

    @property
    def dropped(self) -> int:
        """因引用表已满而没进证据块的切片总数。"""
        return self._dropped

    def _is_full(self) -> bool:
        return len(self._references) >= MAX_REFERENCES

    @property
    def all(self) -> list[Reference]:
        """全量引用表，按编号升序。给前端的 ``reference`` 事件用。"""
        return [self._references[n] for n in sorted(self._references)]

    def _lookup(self, hit: Retrieved) -> Reference:
        chunk_id = hit.chunk.id
        existing = self._numbers.get(chunk_id)
        if existing is not None:
            return self._references[existing]

        ref = self._make(len(self._references) + 1, hit)
        self._numbers[chunk_id] = ref.n
        self._references[ref.n] = ref
        return ref

    @staticmethod
    def _make(n: int, hit: Retrieved) -> Reference:
        chunk = hit.chunk
        return Reference(
            n=n,
            chunk_id=chunk.id,
            source_id=hit.source.id,
            chunk_index=chunk.chunk_index,
            page=chunk.page,
            title=hit.source.title,
            excerpt=_excerpt(chunk.content),
            recall=_recall_label(hit),
        )


def render_evidence(pairs: Sequence[tuple[Reference, Retrieved]]) -> str:
    """渲染喂给 prompt 的编号证据块。

    每块固定「``[n]`` 标题（第 3 页，第 2 段）\\n<正文>」两行。
    出处里带页码与切片序号——模型据此判断「这个数字是第几页的数据」，
    写出来的话才有可核查的出处。

    没有证据时返回空字符串而不是提示文案：调用方靠「是否为空」判断
    该不该告诉模型「你没有资料可用」。
    """
    blocks = [
        f"[{ref.n}] {ref.title}{_location_suffix(ref)}\n{_clip(hit.chunk.content)}"
        for ref, hit in pairs
    ]
    return "\n\n".join(blocks)


def citation_rules(table: ReferenceTable) -> str:
    """写进 tool_result 的引用规则。

    用 ``table.all`` 的长度算上界——模型可能在第三轮才第一次用工具，
    拿「本轮新编的号」当上界会漏掉前面几轮已有的编号。

    必须显式给出「只能引用出现过的编号」这条约束——模型的默认倾向是
    按自己的话写，看到数字就顺手标一个。少了这段，编造引用率会明显上升。
    """
    upper = len(table.all)
    if upper == 0:
        return ""
    overflow = ""
    if table.dropped:
        overflow = (
            f"\n- 资料里还有 {table.dropped} 条相关内容没有展示，不要据此认为资料库只有上面这些。"
        )
    return (
        f"你有一批来自用户私有资料的证据，编号 [1] 到 [{upper}]，"
        f"每条已标注标题与页码。\n"
        f"写作规则：\n"
        f"- 凡是基于这批证据的陈述，必须在句末标上对应编号，如 [1] 或 [1][2]。\n"
        f"- 只能引用 [1]~[{upper}]，**严禁编造不存在的编号**。\n"
        f"- 证据里没有的数字不要写，宁可说「资料未提供」。\n"
        f"- 证据与你的既有知识冲突时，以证据为准。"
        f"{overflow}"
    )


def _location_suffix(ref: Reference) -> str:
    """出处的括号部分。有页码写页码，段序号总是写。"""
    if ref.page is not None:
        return f"（第 {ref.page} 页，第 {ref.chunk_index + 1} 段）"
    return f"（第 {ref.chunk_index + 1} 段）"


def _clip(content: str) -> str:
    return (
        content
        if len(content) <= CHUNK_CONTENT_CHARS
        else content[:CHUNK_CONTENT_CHARS] + "…（已截断）"
    )


def _excerpt(content: str) -> str:
    if len(content) <= EXCERPT_CHARS:
        return content
    return content[:EXCERPT_CHARS] + "…"


def _recall_label(hit: Retrieved) -> str:
    """两路都命中说明证据强，前端可以给更高的置信样式。"""
    if hit.vector_rank is not None and hit.bm25_rank is not None:
        return "向量+BM25"
    return "向量" if hit.vector_rank is not None else "BM25"


# ── 抽取报告里带角标的句子 ──────────────────────────────────

# 行内角标 [1] / [1,2] / [1][2]。
#
# `\d{1,3}` 而非 `\d+`：引用表编号是「每个请求独立从 1 起」的自增序号，
# 实际不会超过三位数。用 `\d+` 会把 "[2024] 年的报告" 里的年份当成编号
# 2024——那是个没人引用的编号，会让校验报告里凭空多一条「引用缺失」。

_FOOTNOTE_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+")


def extract_cited_sentences(text: str) -> dict[int, list[str]]:
    """按引用编号收集带角标的句子。

    返回 ``{引用编号: [句子, ...]}``。同一句里带多个角标时，它会同时
    出现在每个编号下——**这句话确实同时引用了多条资料**，两两都要校验。
    """
    result: dict[int, list[str]] = {}
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for group in _FOOTNOTE_RE.findall(sentence):
            for raw in group.split(","):
                number = int(raw.strip())
                result.setdefault(number, []).append(sentence)
    return result


def count_citation_markers(text: str) -> dict[int, int]:
    """数每个 ``[n]`` 角标在正文里出现了几次。

    ## 为什么落盘要这个，而不是数 ``collected_refs``

    ``local_search`` 每轮返回的是**全量引用表快照**（``tools.py`` 的
    ``references=tuple(context.citations.all)``），不是本轮新增的那几条。
    而 ``agent.py`` 直接把它 extend 进 ``collected_refs``，于是同一个
    chunk 会在每一轮都出现一次——按 refs 长度累加得到的是「这个切片在
    几轮工具结果里出现过」，与「正文引用了它几次」毫无关系。

    复用 :func:`extract_cited_sentences` 的同一套正则，避免两处规则漂移。
    """
    counts: dict[int, int] = {}
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        for group in _FOOTNOTE_RE.findall(sentence):
            for raw in group.split(","):
                counts[int(raw.strip())] = counts.get(int(raw.strip()), 0) + 1
    return counts
