/**
 * sources 页的「后端 → 表格」映射层。
 *
 * ## 为什么不直接渲染后端结构
 *
 * 后端 `SourceV` 是**存储视角**（`chunk_count: number`、`created_at: string`、
 * `status` 6 态）；表格要的是**展示视角**（"87 切片"、"2 小时前"、"已完全索引"）。
 * 混在一起的话每个 cell 都要写一遍格式化，列定义就没法复用。
 *
 * ## 为什么筛选在映射**之前**做
 *
 * `filterSources` 收 `SourceV` 而不是 `SourceRow`：`SourceRow` 的 status
 * 已经压成 3 态、kind 已翻成展示标签，拿它筛就得反推原值。把 `apiStatus`
 * / `apiType` 塞进 `SourceRow` 则是让展示态背两份真相——表格只读 12 个
 * 字段，多加的会让人对不上「表格在读什么」。
 */

import { mapIcon, mapLibraryLabel } from './sourceKind'
import type { SourceStatusV, SourceTypeV, SourceV } from '@/lib/api/sources'

export type ApiSourceStatus = SourceStatusV
export type ApiSourceType = SourceTypeV

/** 表格行的展示状态。后端 6 态压成 3 态。 */
export type RowStatus = 'ready' | 'processing' | 'failed'

export const ROW_STATUS: Record<ApiSourceStatus, RowStatus> = {
  pending: 'processing',
  parsing: 'processing',
  chunking: 'processing',
  embedding: 'processing',
  indexed: 'ready',
  failed: 'failed',
}

/** 后端 6 态 → 表格 3 态。 */
export function toRowStatus(status: ApiSourceStatus): RowStatus {
  return ROW_STATUS[status]
}

/**
 * 表格行。
 *
 * 字段集**精确对齐** `SourceTable` 实际读取的字段（`components/SourceTable/
 * index.tsx` 里所有 `row.*`）。多加的字段看起来无害，实际会让「表格到底在
 * 读什么」这件事对不上账。
 */
export interface SourceRow {
  /** 后端主键。**字符串化后使用**：`PlainTable` 的 `getRowId` 契约是
   *  `(row, index) => string`，直接塞 number 会与选择态的 `Set<string>` 打架。 */
  id: number
  title: string
  /** 副标题：URL 建源显示地址，上传文件**退化成类型标签**。
   *  后端不存原始文件名——`SourceCreate` 只收 `title`，上传端点也只把
   *  文件名塞进 `title`（见 gateway/sources.py 的 upload_source），
   *  所以拿不到「原始文件名 vs 用户改过的 title」这个区分。 */
  meta: string
  kind: string
  /** 体积。URL 建源时后端没有 Content-Length，为 null——表格据此不显示
   *  体积那一行（而不是显示一个「—」，它会跟下面的切片数自相矛盾）。 */
  size: string | null
  chunks: string
  /** 关联报告数，0 时显示「—」而不是 "0 篇"：0 与「没有引用过」在这个
   *  语境下是同一件事，写 0 会被读成「引用了 0 次」。 */
  citations: number
  status: RowStatus
  timeLabel: string
  iconName: string
  iconAccent: string
}

const ICON_ACCENT: Record<RowStatus, string> = {
  ready: 'text-emerald-600',
  processing: 'text-amber-600',
  failed: 'text-red-600',
}

/**
 * 字节数 → 人类可读。**字节不带小数**（"842 B" 比 "842.0 B" 干净）。
 *
 * 千进制（1 KB = 1000 B），与几乎所有云控制台一致——二进制（1024）在
 * 「资料多大」这个语境里没有可验证的上游标准，会让两处数字对不上。
 */
export function formatBytes(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1000
  let unit = 0
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit]}`
}

/**
 * 相对时间（"2 小时前"）。
 *
 * 刻意**手写**而不是用 `Intl.RelativeTimeFormat`：全角/半角与
 * 「刚刚」这类阈值的措辞在这个页面是统一的，手写反而更一致，且省掉
 * 一个 Intl 格式化器在每行 cell 里的开销。
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return '—'
  const seconds = Math.max(0, (now.getTime() - then.getTime()) / 1000)
  if (seconds < 60) return '刚刚'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months} 个月前`
  return `${Math.floor(months / 12)} 年前`
}

/** 后端单条 → 表格行。 */
export function toSourceRow(source: SourceV, now: Date = new Date()): SourceRow {
  const status = toRowStatus(source.status)
  return {
    id: source.id,
    title: source.title,
    meta: source.url ?? mapLibraryLabel(source.source_type),
    kind: mapLibraryLabel(source.source_type),
    size: source.size_bytes === null ? null : formatBytes(source.size_bytes),
    chunks: source.chunk_count > 0 ? `${source.chunk_count} 切片` : '—',
    citations: source.citation_count,
    status,
    timeLabel: formatRelativeTime(source.created_at, now),
    iconName: mapIcon(source.source_type),
    iconAccent: ICON_ACCENT[status],
  }
}

/** 整份列表映射。 */
export function toSourceRows(sources: readonly SourceV[], now: Date = new Date()): SourceRow[] {
  return sources.map((s) => toSourceRow(s, now))
}

// ── 筛选项 ──────────────────────────────────────────────────

/**
 * 类型筛选项。`key` 是 tab 的 key（见下方 `TabKey`），不是后端
 * `source_type` 的原值——`docx` 归进「纯文本」tab，筛选的语义是
 * **用户看到的分类**，不是后端枚举。
 */
export interface SourceTypeFilter {
  key: TabKey
  label: string
}

/**
 * 后端只认 3 种类型（`SourceType`），设计稿列了 5 类。
 *
 * 前两个沿用设计稿原词。`RSS 实时流` / `技术论文 Arxiv` / `音视频转录`
 * 在后端**没有对应**（RSS 没订阅端点、Arxiv 走的是 pdf 的路、音视频没有
 * 转录能力），所以不给它们造 entry——给了就是让用户勾一个永远 0 条的选项。
 * 「纯文本」对应后端的 `text`，涵盖 .md/.txt/.html 之外的纯文稿。
 */
export const SOURCE_TYPE_FILTERS: readonly SourceTypeFilter[] = [
  { key: 'pdf', label: 'PDF 文档' },
  { key: 'html', label: '网页 URL' },
  { key: 'text', label: '纯文本' },
]

/**
 * tab 的 key。**这个字面量联合是 tab 集合的唯一真源**——
 * `SOURCE_TYPE_FILTERS` 与 `TYPE_TO_FILTER` 的值域都从它派生。
 *
 * 之前 `TYPE_TO_FILTER` 的值类型是 `ApiSourceType`（全部后端类型），与 tab
 * 的 key 域没有任何类型关系——`{ pdf: 'pdf', ..., docx: 'epub' }` 能过类型
 * 检查，但 'epub' 不在 tab 里，那份资料既点不出来、计数也不会显示。
 * 值域收窄到 TabKey 后，那种错误直接编译失败。
 *
 * 不能反过来从 `SOURCE_TYPE_FILTERS` 派生（`(typeof ARR)[number]['key']`）——
 * 那样 `SourceTypeFilter.key` 的类型又得引用 TabKey，成了循环引用。
 * 所以真源是这个字面量联合，数组只是它的使用处。
 */
export type TabKey = 'pdf' | 'html' | 'text'

/**
 * 后端类型 → 它归属的筛选 tab。
 *
 * **必须显式列全**。`SOURCE_TYPE_FILTERS` 是手写的数组，加了新
 * `SourceType` 却忘了往这里补，那个类型就既不在 tab 里、也点不出来——
 * `counts[tab]` 恒为 0，而资料明明在库里。
 *
 * docx 归入「纯文本」：它在用户眼里就是一份文档，开第四个 tab 只让筛选
 * 栏变长而不改变筛选结果。
 */
export const TYPE_TO_FILTER: Record<ApiSourceType, TabKey> = {
  pdf: 'pdf',
  html: 'html',
  text: 'text',
  docx: 'text',
}

/**
 * 展示态筛选器。`key` 是 `RowStatus`。
 *
 * 勾选集合里**存展示态**（3 态）而不是后端态（6 态）：用户按**结果**分
 * （能不能用 / 在不在忙 / 坏了），「解析中」和「向量化中」不该是两个
 * 独立的勾选项。所以映射是 6→3 而不是 6→6。
 *
 * label 用设计稿原词（Indexed / Processing / Failed），不改成「已就绪」
 * 「处理中」那种更「规范」的措辞——用户看的是这份稿子，不是术语表。
 */
export interface RowStatusFilter {
  key: RowStatus
  label: string
}

export const ROW_STATUS_FILTERS: readonly RowStatusFilter[] = [
  { key: 'ready', label: '已完全索引' },
  { key: 'processing', label: '增量切片中' },
  { key: 'failed', label: '索引告警' },
]

/**
 * 按筛选条件过滤**后端对象**。
 *
 * 任一维度传空数组表示「不过滤这一维」——这样「取消全选」与「不过滤」
 * 不会混淆成同一个状态。
 */
export function filterSources(
  sources: readonly SourceV[],
  types: ReadonlySet<TabKey>,
  statuses: ReadonlySet<RowStatus>,
): SourceV[] {
  return sources.filter((s) => {
    // 经 TYPE_TO_FILTER 归并，所以 docx 会被「纯文本」tab 选中——
    // 直接比 source_type 的话 docx 永远被排除在任何 tab 之外。
    if (types.size > 0 && !types.has(TYPE_TO_FILTER[s.source_type])) return false
    if (statuses.size > 0 && !statuses.has(toRowStatus(s.status))) return false
    return true
  })
}

/**
 * 各**筛选 tab** 的条数，不是各后端类型的条数。
 *
 * 走 TYPE_TO_FILTER 归并，所以 docx 计进「纯文本」——与
 * `matchesFilters` 用的是同一套归并，否则 tab 上的数字会和点进去看到的
 * 行数对不上（数字少算，点进去却变多）。
 */
export function countByType(sources: readonly SourceV[]): Record<TabKey, number> {
  const counts: Record<TabKey, number> = {
    pdf: 0,
    html: 0,
    text: 0,
  }
  for (const s of sources) counts[TYPE_TO_FILTER[s.source_type]] += 1
  return counts
}

/** 各展示态的条数。 */
export function countByStatus(sources: readonly SourceV[]): Record<RowStatus, number> {
  const counts: Record<RowStatus, number> = { ready: 0, processing: 0, failed: 0 }
  for (const s of sources) counts[toRowStatus(s.status)] += 1
  return counts
}

/** 整份列表的字符数合计，用于页头与底栏。 */
export function sumCharCount(sources: readonly SourceV[]): number {
  return sources.reduce((total, s) => total + s.char_count, 0)
}
