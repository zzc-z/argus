/**
 * 极简 Markdown 解析。
 *
 * 后端 system prompt 明确要求「用 Markdown 组织内容，该用小标题和列表就用」
 * （`apps/api/app/services/agent.py`），所以正文里必然出现 `##` 与 `- `。
 * 原样塞进 <p> 会把 Markdown 源码直接显示给用户。
 *
 * ## 为什么不引 markdown 库
 *
 * react-markdown + remark 一套要新增 8+ 个依赖。本页只需要标题、列表、
 * 段落、加粗、行内代码这 5 种，加上引用角标——自己写可控，
 * 引库则要为「渲染模型输出」引入一整条 XSS 防线（库默认会渲染原始 HTML，
 * 又要额外配 rehype-sanitize）。模型输出直接进 DOM 本身就是不可信输入。
 *
 * 这里的产物只是纯数据（块 + 行内 token），落到 DOM 的元素由组件用 React
 * 文本节点生成，**没有任何 dangerouslySetInnerHTML**——模型输出里的
 * `<script>` 只会显示成字面量。
 *
 * ## 支持范围
 * `#`~`####` 标题、`-` / `*` 无序列表、`1.` 有序列表、GFM 管道表格、
 * `**粗体**`、`` `行内代码` ``、空行分段。其余语法（链接、代码块、引用块）
 * 按纯文本处理——模型极少产出这些，真出现了也不该让用户看到裸语法。
 *
 * ## 为什么表格算必需而非锦上添花
 *
 * 实测（2026-10-19，本地跑一轮真实提问）：模型输出的「检索结果对照」就是
 * 一张表，不支持时整段 `| 检索词 | 召回内容 |` 会以裸语法糊在正文里。
 * 本项目的核心场景是「多份资料横向对比」，表格是主力输出形态。
 */

export type Block =
  | { kind: 'heading'; level: 2 | 3 | 4; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'table'; header: string[]; rows: string[][] }

/** 行内 token。`text` 之外的类型由渲染层决定怎么画。 */
export type InlineToken =
  | { kind: 'text'; value: string }
  | { kind: 'bold'; value: string }
  | { kind: 'code'; value: string }

/**
 * 标题。`#{1,6}` 而不是 `#{1,4}`——五级六级标题不常见，但模型真写出来时
 * 原样显示 `##### 五级标题` 比降级成四级更糟（用户会以为页面坏了）。
 * 层级在渲染时夹到 2~4。
 */
const HEADING_RE = /^(#{1,6})\s+(.*)$/
const UL_RE = /^\s*[-*]\s+(.*)$/
const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`)/g
/**
 * 表格分隔行，如 `|---|---|:--:|`。
 *
 * 必须**逐格**匹配：每格只能是 `-` / `:` / 空白，且至少 3 个 `-`。
 * 放宽成「整行含 `-` 就算」会把 `成本 | 收入` 后跟 `---` 的普通文本
 * 误判成表格（渲染出一个只有表头没有行的空表）。
 */
const TABLE_DELIM_RE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/
/** 表格行：至少要有两个管道，否则一行文字里的单个 `|` 会被当成表。 */
const TABLE_ROW_RE = /^\s*\|.*\|.*$/
/**
 * 有序列表项。数字后必须跟 `.` 或 `)` **且带空格**——
 * `2024. 年度报告` 会被误判成列表项，少了空格就不算。
 */
const OL_ITEM_RE = /^\s*(\d{1,9})[.)]\s+(.*)$/

/** 切一行管道表格。首尾的 `|` 与空白都去掉，`\|` 暂按普通字符处理。 */
function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())
}

/**
 * 把 Markdown 文本切成块。
 *
 * 列表项的续行（缩进但不是新列表项）会并入当前项——模型偶尔在列表项里
 * 换行，丢掉续行会让句子断在半截。
 */
export function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = []
  const lines = markdown.split('\n')
  let paragraph: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null

  const flushParagraph = () => {
    if (paragraph.length === 0) return
    blocks.push({ kind: 'paragraph', text: paragraph.join('\n') })
    paragraph = []
  }
  const flushList = () => {
    if (!list) return
    blocks.push(list.ordered ? { kind: 'ol', items: list.items } : { kind: 'ul', items: list.items })
    list = null
  }

  // 表格从当前行开始连续吃到没有表格行为止。返回消费的下一行下标。
  //
  // 行必须是**真表格行**（首尾都有管道）。少了这个限制，表格后面紧跟的
  // `- 选项 | 甲` 会被当成表格行吞进去——列表项少了一行还多了个假单元格。
  const readTable = (start: number): { block: Block; next: number } => {
    const header = splitRow(lines[start] ?? '')
    const rows: string[][] = []
    let i = start + 2 // 跳过 `|---|---|` 分隔行
    for (; i < lines.length; i += 1) {
      const l = lines[i]
      if (l === undefined || !TABLE_ROW_RE.test(l)) break
      rows.push(splitRow(l))
    }
    return { block: { kind: 'table', header, rows }, next: i }
  }

  for (let idx = 0; idx < lines.length; idx += 1) {
    const line = lines[idx]
    if (line === undefined) continue
    const trimmed = line.trim()

    if (trimmed === '') {
      flushParagraph()
      flushList()
      continue
    }

    // 表格：当前行是真表格行、下一行是分隔行。
    const next = lines[idx + 1]
    const isTableStart = TABLE_ROW_RE.test(line) && next != null && TABLE_DELIM_RE.test(next)
    if (isTableStart) {
      flushParagraph()
      flushList()
      const { block, next: consumed } = readTable(idx)
      blocks.push(block)
      idx = consumed - 1
      continue
    }

    const heading = HEADING_RE.exec(trimmed)
    const headingText = heading?.[2]
    if (headingText) {
      flushParagraph()
      flushList()
      const level = Math.min(4, Math.max(2, heading?.[1]?.length ?? 2)) as 2 | 3 | 4
      blocks.push({ kind: 'heading', level, text: headingText })
      continue
    }

    const ul = UL_RE.exec(line)
    const ulText = ul?.[1]
    if (ulText) {
      flushParagraph()
      if (!list || list.ordered) {
        flushList()
        list = { ordered: false, items: [] }
      }
      list.items.push(ulText)
      continue
    }

    const ol = OL_ITEM_RE.exec(line)
    const olText = ol?.[2]
    // 有序列表的**首项**必须是 1（或已在有序列表中）。否则 `2024. 年度报告`
    // 这种以年份开头的句子会被当成列表项，句子凭空消失。
    const startsOrderedList = ol?.[1] === '1'
    const continuesOrderedList = list !== null && list.ordered
    if (olText && (startsOrderedList || continuesOrderedList)) {
      flushParagraph()
      if (!list || !list.ordered) {
        flushList()
        list = { ordered: true, items: [] }
      }
      list.items.push(olText)
      continue
    }

    // 缩进但仍是普通文字：并入上一个列表项，否则并入段落。
    if (list && /^\s+\S/.test(line)) {
      const last = list.items.length - 1
      list.items[last] = `${list.items[last]} ${trimmed}`
      continue
    }

    flushList()
    paragraph.push(trimmed)
  }

  flushParagraph()
  flushList()
  return blocks
}

/** 把一段文字切成行内 token（粗体 / 行内代码 / 纯文本）。 */
export function parseInline(text: string): InlineToken[] {
  return text
    .split(INLINE_RE)
    .filter((part) => part !== '')
    .map((part) => {
      if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
        return { kind: 'bold', value: part.slice(2, -2) }
      }
      if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
        return { kind: 'code', value: part.slice(1, -1) }
      }
      return { kind: 'text', value: part }
    })
}
