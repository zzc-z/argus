"""数字与日期的确定性一致性检查。

## 为什么数字要单独走一条通道

CRITIC 最致命的一类错误是**数字错**（原文 2.5 倍 → 句子 100 倍）。
对照实验实测：这类改动的嵌入相似度是 0.9996——**几乎抓不到**。
方向说反（「提升」→「下降」）是 0.9866，同样抓不到。

**数字是可以被程序精确比对的，方向不行。** 所以数字类断言走确定性
通道，其余仍由 LLM 判：既提高了最致命那类的准确率，又不牺牲覆盖面。

## 判据有多强：只做减法

它只判**明确不一致**，从不判「一致」：

- 日期不一致 → 不一致（2024 年 vs 2025 年）
- 量级不同 → 不一致（2.5 倍 vs 100 倍）
- 单位不同 → 不一致（32.1 亿元 vs 32.1 亿美元）
- 句子里对同一单位多引用了一个原文没有的数值 → 不一致（编造数字）

判不准的一律**放行**，交给 LLM——**误伤方向是质疑用户自己写的结论**，
比漏判糟得多。放行的四类：

- 原文根本没提这个单位（分不清是编造还是换了说法）
- 原文是区间（3-5 倍里取 4 倍是合理的）
- 近似说法（约 25%、超过 30%）
- 与内容无关的数（页码、条目序号、裸数）

它**从不产生 supported 的结论**——那需要判断语义对应关系，程序做不了。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# ── 词法 ──────────────────────────────────────────────────────

# 角标：[1] / [1,2]。角标里的数字不是内容的一部分，必须先剥掉——
# 否则「提升 2.5 倍[1]」会被读成两个数（2.5 与 1）。
#
# **必须与 ``citation._FOOTNOTE_RE`` 保持一致**（1-3 位）。用 `\d+` 会把
# 「[2024] 年的报告」里的年份当成角标剥掉——那个 2024 是**内容**不是
# 编号，剥掉会让真日期错漏判。
_FOOTNOTE_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")

# 千分位：1,200 / 1,200,000。
# 只在「后面恰好三位且不再跟数字」时去掉逗号，避免把「1,2000」这类
# 写错的部分从中间切开（切开后会读成 1 与 2000 两个数）。
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

# 数字本体：整数或小数。不含正负号——「-3%」是「下降 3%」，
# 减号是方向词不是数值的符号。
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# 区间：3-5 倍 / 3~5 倍 / 3—5 倍。
#
# 区间端点必须**整体放行**：「3-5 倍」里取 4 倍是合理的，程序没有
# 依据说它是错的。而且端点被拆出来时「3」会丢掉单位变成裸数——
# 裸数会让「多余数字」的计数判据失准，所以区间整段按软数处理。
_RANGE_RE = re.compile(r"\d+(?:\.\d+)?\s*[-–—~～]\s*\d+(?:\.\d+)?")

# 单位表：(字面量, 类别, 尺度, 族)。按字面量长度降序匹配——
# 「亿元」必须先于「亿」命中，否则「32.1 亿元」会被读成「32.1 亿 + 元」。
#
# ## 类别 vs 族
#
# **族**是「同一个量」——只有同族的两个数才谈得上比量级、比冲突。
# 「元 / 万元 / 亿元」同族（都是人民币金额）；「亿 / 万」**没有族**。
#
# ## 为什么「亿」「万」没有族
#
# 中文里「1.2 亿」既可能是金额也可能是人数（「累计用户 1.2 亿」），
# 程序无从知道。所以这类**歧义单位不参与跨单位比较**——只有当句与原文
# 用的是**同一个 token**（都是「亿」或都是「万元」）时才比。
#
# 否则会误伤：「累计用户 1.2 亿，营收 32.1 亿元」会被判成「量级不一致」，
# 而「用户数」与「营收」根本不是同一个量。
#
# 「个百分点」与「%」也分开：前者是差值、后者是比率，量纲不同。
_UNIT_TABLE: tuple[tuple[str, str, float, str], ...] = (
    ("个百分点", "percent_point", 1.0, "percent_point"),
    ("万亿元", "cny", 1e12, "cny"),
    ("亿美元", "usd", 1e8, "usd"),
    ("亿元", "cny", 1e8, "cny"),
    ("万元", "cny", 1e4, "cny"),
    ("万美元", "usd", 1e4, "usd"),
    ("美元", "usd", 1.0, "usd"),
    ("人民币", "cny", 1.0, "cny"),
    ("个月", "count", 1.0, "count"),
    ("万亿", "scale", 1e12, ""),
    ("％", "percent", 1.0, "percent"),
    ("%", "percent", 1.0, "percent"),
    ("倍", "ratio", 1.0, "ratio"),
    ("元", "cny", 1.0, "cny"),
    ("亿", "scale", 1e8, ""),
    ("万", "scale", 1e4, ""),
    ("年", "date_year", 1.0, "date_year"),
    ("月", "date_month", 1.0, "date_month"),
    ("日", "date_day", 1.0, "date_day"),
    ("人", "count", 1.0, "count"),
    ("个", "count", 1.0, "count"),
    ("家", "count", 1.0, "count"),
    ("次", "count", 1.0, "count"),
    ("台", "count", 1.0, "count"),
    ("件", "count", 1.0, "count"),
)
_UNIT_TOKENS: tuple[tuple[str, str, float, str], ...] = tuple(
    sorted(_UNIT_TABLE, key=lambda item: -len(item[0]))
)


# 量纲相容表：「scale」（没说是哪种钱的中文量级后缀）与哪种币种相容。
#
def _same_quantity(a: _Num, b: _Num) -> bool:
    """两个数是不是**同一个量**——只有同一个量才谈得上比量级。

    ## 判据

    1. **同族**（cny / usd / percent / count / date_*）→ 是同一个量
    2. **歧义单位**（「亿」「万」）→ 只有**单位字面相同**时才是同一个量
    3. 其余（不同族、裸数、百分点 vs 百分比）→ 不是同一个量

    ## 为什么歧义单位要单独处理

    中文里「1.2 亿」既可能是金额（「营收 1.2 亿」）也可能是人数
    （「累计用户 1.2 亿」）。程序无从知道。

    按「量纲相容」放它过去会误伤：「累计用户 1.2 亿，营收 32.1 亿元」
    会被判成「量级不一致」——**用户数**与**营收**根本不是同一个量。

    按「单位字面相同」收紧就安全：句子的「1.2 亿」只会与原文的「亿」比，
    不会与「亿元」比。
    """
    if a.family and b.family:
        return a.family == b.family
    if a.category == "scale" and b.category == "scale":
        return a.token == b.token
    return False


def _conflicting_unit(a: _Num, b: _Num) -> bool:
    """两个数是不是**同一个量配了不同的单位**。

    ## 判据

    **归一值相等**（同一个量）+ **币种明确不同** → 单位写错了。

    - 「32.1 亿元」vs「32.1 亿美元」：归一值都是 3.21e9，币种不同 → 冲突
    - 「32.1 万元」vs「32.1 亿美元」：归一值差 1e4 → 也是冲突（币种 + 量级都错）
    - 「2.5 个百分点」vs「2.5%」：归一值相等，族不同 → 冲突

    ## 歧义单位（「亿」「万」）怎么处理

    它们**隐含 cny**（中文里「32.1 亿」默认是亿元），所以：

    - 「32.1 亿」vs「32.1 亿元」→ 归一值相等、币种都是 cny → **不冲突**
      （同一句话的两种写法）
    - 「32.1 亿」vs「32.1 亿美元」→ 归一值相等、cny vs usd → **冲突**

    但「1.2 亿」（用户数）vs「32.1 亿元」（营收）→ 归一值不等 → 压根不比较，
    放行。

    ## 裸数不参与

    裸数没有单位，「第 3 页」对「3 倍」不是单位冲突。
    """
    if not a.token or not b.token:
        return False
    if a.family == b.family:
        return False
    # 歧义单位（「亿」「万」）只在与**明确币种**比较时才可能冲突。
    #
    # 「1.2 万」vs「12000 人」——归一值相等，但「1.2 万」说的是不是人，
    # 程序无从知道（也可能是 1.2 万元）。判成冲突是误伤。
    # 而「32.1 亿」vs「32.1 亿美元」——一边隐含 cny、一边明确是 usd，
    # 那是真冲突。
    a_is_ambiguous = a.family == ""
    b_is_ambiguous = b.family == ""
    if a_is_ambiguous or b_is_ambiguous:
        other = b if a_is_ambiguous else a
        if other.family not in ("cny", "usd"):
            return False
        # 歧义单位隐含 cny——与 cny 不冲突，与 usd 冲突
        if other.family == "cny":
            return False
    # 「同一个数配了不同单位」有两种形态：
    # - 归一值相等（32.1 亿元 vs 32.1 亿美元）：量级相同、单位不同
    # - 原值相等但量级也不同（32.1 万元 vs 32.1 亿美元）：量级也差了
    return _close(a.normalized, b.normalized) or _close(a.value, b.value)


# 近似限定词。出现在数字**前面**时说明原文自己都没给准（「约 25%」），
# 出现在**后面**时同理（「30% 以上」）。这类数一律**放行**：
# 拿限定过的数做精确比对，比对结果没有意义。
#
# 「多」「余」不收进后置表——「营收 32.1 亿美元，多家机构……」会让
# 32.1 被误判成近似数，从而漏掉真正的量级错误。
_APPROX_BEFORE: tuple[str, ...] = (
    "大约",
    "接近",
    "将近",
    "超过",
    "超出",
    "至少",
    "最多",
    "不到",
    "约",
    "近",
    "逾",
)
_APPROX_AFTER: tuple[str, ...] = (
    "以上",
    "以下",
    "左右",
    "上下",
    "以内",
    "以外",
    "出头",
)

# 「近」既是近似限定词（「近 25%」），也是「最近」的一部分。
# 「最近 5 年」里的 5 是确定的时间范围，标成近似会漏掉日期错误，
# 所以要单独排除这一个词。
_NOT_APPROX_WORDS: tuple[str, ...] = ("最近",)

# 时长语境：数的是**一段时间**，不是某个日期。
#
# 「最近 5 年」与「最近 3 年」是两个不同的陈述，原文说 3 年、句子说 5 年
# 可能是合法的（引用的是原文另一段），而按日期判据会判「不一致」——
# **误伤方向是质疑用户自己写的结论**，比漏判糟得多。
#
# 「未来 3 年」「过去 10 个月」同理。
_DURATION_PREFIXES: tuple[str, ...] = (
    "最近",
    "过去",
    "未来",
    "此前",
    "今后",
    "往后",
    "往前",
    "近",
)

# 量级阈值：相差 10 倍以上才算「量级不同」。
#
# 为什么是 10：2.5 倍 → 100 倍是 40 倍，必须抓住；而 25% → 22% 这类
# 小幅差异**不抓**——它可能只是口径不同，拿程序去判「到底哪个对」
# 就是误伤。
_MAGNITUDE_RATIO = 10.0

# 看限定词时回看多少个字符。
#
# 「最近的 5 年」的数字前面是「最近的 」（4 字符）——窗口小于 4 会把
# 「过去」截成「去」而漏判。6 覆盖「最近的 5 年」这类最长的情况。
_LOOKBACK_CHARS = 6

# 闭合符号。数字与它的单位之间可能隔着这些——
# 「[2024] 年」里的 2024 是内容不是角标，单位「年」隔着 `]`。
_CLOSING_MARKS: tuple[str, ...] = ("]", "】", "）", ")", "）")


# ── 数据结构 ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NumericVerdict:
    """数字一致性判定结果。

    ``mismatch`` 为 False 时**不代表数字一致**，只代表**程序判不出来**——
    这种情况要交给 LLM 判。本通道只做减法：它能确认「不一致」，
    不能确认「一致」。
    """

    mismatch: bool
    detail: str = ""
    sentence_numbers: tuple[float, ...] = ()
    source_numbers: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class _Num:
    """一个被抽出来的数及其上下文。"""

    value: float
    raw: str
    token: str
    """单位字面量。空串表示**没有单位**（裸数）。"""
    category: str
    """单位类别：percent / percent_point / ratio / cny / usd / scale /
    date_* / count / bare。"""
    family: str
    """「同一个量」的族：cny / usd / percent / percent_point / ratio /
    count / date_*。

    **空串 = 歧义单位**（「亿」「万」）——中文里「1.2 亿」可能是金额也
    可能是人数，程序无从知道，所以不参与跨单位比较（见 :data:`_UNIT_TABLE`）。
    """
    scale: float
    soft: bool
    """带近似限定词（"约 25%"）——不参与比对。"""
    duration: bool
    """数的是**一段时间**（"最近 5 年"）而不是某个日期。

    这种数**不参与日期判据**——「最近 5 年」与「最近 3 年」是两个不同的
    陈述，拿日期规则去比会误伤用户自己写的结论。
    """

    @property
    def normalized(self) -> float:
        """按单位尺度归一后的值。「1 万元」与「10000 元」归一后相等。"""
        return self.value * self.scale

    @property
    def currency(self) -> str:
        if self.category == "cny":
            return "CNY"
        if self.category == "usd":
            return "USD"
        return ""


# ── 抽取 ──────────────────────────────────────────────────────


def extract_numbers(text: str) -> list[float]:
    """抽出文本里的所有数（不含单位信息）。

    剥离千分位逗号、忽略角标 ``[1]``。单位信息是**比对**时才需要的，
    对外暴露的接口只给数值本身。
    """
    return [n.value for n in _extract(text)]


def _extract(text: str) -> list[_Num]:
    """抽出文本里的数及其单位/近似限定。"""
    cleaned = _FOOTNOTE_RE.sub(" ", text)
    cleaned = _THOUSANDS_RE.sub("", cleaned)

    out: list[_Num] = []
    for match in _NUMBER_RE.finditer(cleaned):
        raw = match.group()
        after = cleaned[match.end() :]
        token, category, scale, family = _match_unit(after)
        out.append(
            _Num(
                value=float(raw),
                raw=raw,
                token=token,
                category=category,
                family=family,
                scale=scale,
                soft=_is_soft(cleaned, match.start(), after)
                or _in_range(cleaned, match.start(), match.end()),
                duration=_is_duration(cleaned, match.start()),
            )
        )
    return out


def _in_range(text: str, start: int, end: int) -> bool:
    """这个数是不是某个区间的端点。

    区间端点**整段放行**：原文写「3-5 倍」时，句子取 4 倍是合理的，
    程序没有依据说它错。而端点被单独抽出来会丢掉单位（「3-5 倍」里的
    「3」变成裸数），裸数又会让「多余数字」的计数判据失准。
    """
    return any(m.start() <= start and end <= m.end() for m in _RANGE_RE.finditer(text))


def _prefix_before(text: str, start: int) -> str:
    """取数字前面那一小段限定词，去掉尾部的「的」。

    ## 为什么要去掉「的」

    中文里限定词与数字之间常插「的」（「过去的 5 年」「最近的 3 个月」）。
    不去掉的话 ``endswith("过去")`` 恒为假——判据静默失效。

    ## 窗口要够宽

    ``_LOOKBACK_CHARS`` 覆盖「最近的 5 年」这类最长的情况（2 字限定词
    + 「的」+ 空格）。
    """
    prefix = text[max(0, start - _LOOKBACK_CHARS) : start].strip()
    return prefix.removesuffix("的").strip()


def _is_duration(text: str, start: int) -> bool:
    """这个数前面是不是时长限定词（"最近 5 年" / "过去 3 个月"）。

    时长里的数**不是日期**：「最近 5 年」与「最近 3 年」是两个不同的
    陈述，按日期规则去比会误伤用户自己写的结论。
    """
    prefix = _prefix_before(text, start)
    return any(prefix.endswith(marker) for marker in _DURATION_PREFIXES)


def _match_unit(after: str) -> tuple[str, str, float, str]:
    """匹配数字后面紧跟的单位。返回 ``(字面量, 类别, 尺度, 族)``。

    ## 要跨过闭合符号

    「[2024] 年」里的 2024 是**年份内容**（方括号里超过 3 位就不是角标，
    见 :data:`_FOOTNOTE_RE`），它的单位「年」隔着 `]`。不跨过去的话
    2024 会变成裸数，与原文的「2025 年」配不上——真日期错就漏判了。
    """
    rest = after.lstrip()
    while rest[:1] in _CLOSING_MARKS:
        rest = rest[1:].lstrip()
    for token, category, scale, family in _UNIT_TOKENS:
        if rest.startswith(token):
            return token, category, scale, family
    return "", "bare", 1.0, ""


def _is_soft(text: str, start: int, after: str) -> bool:
    """这个数是否带近似限定词。

    前后各看一眼：中文里「约 25%」与「25% 以上」都很常见。

    限定词与数字之间也可能有「的」（「近的 25%」不太常见，但
    「大约 25%」「最近的 5 年」这类结构里「的」会出现），所以
    判定前同样去掉尾部的「的」。
    """
    prefix = _prefix_before(text, start)
    if any(prefix.endswith(marker) for marker in _APPROX_BEFORE):
        return not any(prefix.endswith(word) for word in _NOT_APPROX_WORDS)
    return any(marker in after[:6] for marker in _APPROX_AFTER)


# ── 判定 ──────────────────────────────────────────────────────


def check_numeric_consistency(sentence: str, source: str) -> NumericVerdict:
    """比对一句断言与它所引用的原文，判数字是否**明确不一致**。

    ``False`` 表示「程序判不出来」，**不是**「数字一致」。

    判定顺序按「误伤代价从低到高」排：日期先判（日期错是硬伤且几乎
    不会误伤），再判量级与单位，最后才判「多出来的数字」（这一类最
    可能误伤，因为它依赖「原文提到过这个单位」这个前提）。
    """
    s_all = _extract(sentence)
    t_all = _extract(source)
    numbers = (tuple(n.value for n in s_all), tuple(n.value for n in t_all))

    s_nums = [n for n in s_all if not n.soft]
    t_nums = [n for n in t_all if not n.soft]
    if not s_nums:
        return NumericVerdict(
            mismatch=False, detail="", sentence_numbers=numbers[0], source_numbers=numbers[1]
        )

    unmatched = [s for s in s_nums if not _is_matched(s, t_nums)]
    detail = _check_dates(unmatched, t_nums)
    if not detail:
        detail = _check_magnitude(unmatched, t_nums)
    if not detail:
        detail = _check_unit_conflict(unmatched, t_nums)
    if not detail:
        detail = _check_extra(s_nums, unmatched, t_nums)

    return NumericVerdict(
        mismatch=bool(detail),
        detail=detail,
        sentence_numbers=numbers[0],
        source_numbers=numbers[1],
    )


def _is_matched(s: _Num, t_nums: list[_Num]) -> bool:
    """这个句子侧的数能否在原文里找到对应的数。

    「对应」指**数值相等**：同单位同值，或同一个量且归一后相等
    （「1 万元」=「10000 元」；「32.1 亿」=「32.1 亿元」）。

    **时长与日期不互配**：「5 年」（时长）不该被「2024 年」（日期）匹配上
    ——值本来就不同，但类别相同会让归一化那条路把它们凑成一对。
    """
    for t in t_nums:
        if s.duration is not t.duration:
            continue
        if s.token == t.token and _close(s.value, t.value):
            return True
        if _same_quantity(s, t) and _close(s.normalized, t.normalized):
            return True
    return False


def _check_dates(unmatched: list[_Num], t_nums: list[_Num]) -> str:
    """日期必须**精确相等**——年份差 1 也是错。

    日期不走量级规则：2024 与 2025 的比值是 0.9995，量级规则根本不会
    触发，而「原文说 2024 年、句子说 2025 年」正是最该抓的那类错。

    **时长不算日期**：「最近 5 年」里的 5 是时间段，不是日期点，
    拿日期规则去比会误伤（「最近 5 年」vs「最近 3 年」是两个陈述）。
    """
    for s in unmatched:
        if not s.category.startswith("date_") or s.duration:
            continue
        candidates = [t for t in t_nums if t.category == s.category and not t.duration]
        if not candidates:
            # 原文没提这个日期 → 放行。程序分不清「原文没提所以是编的」
            # 与「原文用别的说法说了同一件事」。
            continue
        source_dates = "、".join(dict.fromkeys(t.raw for t in candidates))
        return f"日期不一致：句子的「{s.raw}」与原文的「{source_dates}」对不上"
    return ""


def _check_magnitude(unmatched: list[_Num], t_nums: list[_Num]) -> str:
    """同一个量下，归一值相差 10 倍以上 → 量级不一致。

    ## 按**归一值**比，不按单位字面比

    同族的不同量级单位（元 / 万元 / 亿元）字面不同但可比：
    原文「32.1 亿元」写成「32.1 元」，字面 token 不相等（"元" vs "亿元"），
    按字面比会漏掉这个错——而它正是「单位量级搞错」最常见的形态。

    所以这里比的是**归一后的值**（32.1 亿元 = 3.21e9，32.1 元 = 32.1），
    比值 1e8 ≥ 10 → 判定不一致。

    ## 只与**同一个量**比

    比量级的前提是两边说的是同一个量。「累计用户 1.2 亿」与「营收
    32.1 亿元」不是同一个量——把它们放一起比会误伤。
    判定见 :func:`_same_quantity`。

    ## 理由要指向**最相关**的那个原文数

    遍历时选**归一值比值最小**的那个（最接近的候选），而不是第一个
    命中的。理由指错方向比判错更麻烦——用户按提示去核对会核不到问题。
    """
    for s in unmatched:
        best: tuple[float, _Num] | None = None
        for t in t_nums:
            if not s.token or not t.token:
                continue
            # 只与同一个量比——「用户数」与「营收」不是同一个量。
            if not _same_quantity(s, t):  # 量级判据的同量筛选
                continue
            # 时长与日期不互比：「最近 5 年」的 5 与「2025 年」的 2025
            # 同属 date_year 类别，归一后差 400 倍——但那是两回事，
            # 不是量级错误。
            if s.duration != t.duration:
                continue
            ratio = _ratio(s.normalized, t.normalized)
            if ratio is None or ratio < _MAGNITUDE_RATIO:
                continue
            # **取比值最小（最接近）的那一个**——那才是用户该去核对的那个数。
            if best is None or ratio < best[0]:
                best = (ratio, t)
        if best is not None:
            # **带上单位**：归一后可比，但用户看到的是原始写法，
            # 「32.1 与 32.1 相差过大」根本看不出哪里错。
            t = best[1]
            return f"量级不一致：句子的「{s.raw}{s.token}」与原文的「{t.raw}{t.token}」相差过大"
    return ""


def _check_unit_conflict(unmatched: list[_Num], t_nums: list[_Num]) -> str:
    """同一个数配了不同的单位 → 单位不一致。

    判据是**原值相等但族不同**：「32.1 万元」与「32.1 亿美元」原值都是
    32.1，归一后差 1e4——单位写错了。

    「32.1 亿元」与「32.1 亿美元」原值相同、族不同 → 真冲突。

    **裸数不参与**：裸数没有量纲信息，「第 3 页」对「3 倍」不是量纲冲突。

    ## 「亿」与「亿元」不是冲突

    中文里「32.1 亿」默认就是亿元——它们是同一句话的两种写法。
    判成量纲冲突是对用户自己写的结论的误伤。而「32.1 亿美元」与
    「32.1 亿元」是**真冲突**（差一整个汇率），必须抓到。
    """
    for s in unmatched:
        if not s.token:
            continue
        for t in t_nums:
            if not t.token:
                continue
            if _conflicting_unit(s, t):  # 单位冲突判定
                return (
                    f"单位不一致：句子的「{s.raw}{s.token}」"
                    f"与原文的「{t.raw}{t.token}」不是同一个单位"
                )
    return ""


def _check_extra(s_nums: list[_Num], unmatched: list[_Num], t_nums: list[_Num]) -> str:
    """句子里对同一单位多引用了一个原文没有的数值 → 编造数字。

    判据不是「原文没有这个数」（那会误伤「原文用别的说法表达了同一
    件事」），而是「**原文提到过这个单位**，而句子引用的次数比原文多」。

    原文提到过「亿美元」一次、句子说了两次「亿美元」——多出来的那个数
    只能是编的。原文压根没提过「%」时，句子里的「%」不算数（放行）。

    ## 这个判据依赖的前提

    **句子的数字都来自它引用的那些原文。**

    一句话带多个角标时，:func:`app.services.faithfulness._numeric_detail`
    会把**全部**被引用的原文拼起来再比对，所以「数字来自另一条原文」
    不会误判。

    但如果模型**漏标角标**（一句话综合了两条原文的内容却只标了一个），
    程序会认为多出来的那个数是编的，而它其实有出处——**这是已知误伤
    形态**。

    之所以仍然判：命中确定性的条目**不进 LLM 复核**，直接呈现给用户，
    所以判据偏严比偏松安全——「原文没有的数字」本身就是研报最典型的
    编造形态，且带角标的句子本来就该只说它引用的内容。
    """
    s_counts = Counter(n.token for n in s_nums)
    t_counts = Counter(n.token for n in t_nums)
    for s in unmatched:
        if not s.token:
            continue
        if t_counts[s.token] < 1:
            # 原文根本没提这个单位 → 放行，交给 LLM 判。
            continue
        if s_counts[s.token] > t_counts[s.token]:
            return f"原文里没有对应的数字：句子的「{s.raw}」"
    return ""


def _ratio(a: float, b: float) -> float | None:
    """两个数的比值（大的除以小的）。两者都是 0 时返回 None。"""
    if a == 0 and b == 0:
        return None
    if a == 0 or b == 0:
        return float("inf")
    return max(a, b) / min(a, b)


def _close(a: float, b: float) -> bool:
    """浮点相等判定（相对容差）。"""
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
