/**
 * add-sources 页的队列行：后端 `SourceV` 的展示态映射。
 *
 * ## 为什么进度条是「不定长」而不是百分比
 *
 * 后端 `SourceStatus` 只有 6 个**阶段**（pending/parsing/chunking/
 * embedding/indexed/failed），**没有百分比**——`ingest.py` 的
 * `_set_status` 每次只写阶段名，同步提交一次。所以「37%」这种数字
 * 在后端不存在来源，画上去就是假的。
 *
 * 这里给的是**阶段名**（「正在切片」），让它告诉用户「在动、动到哪一步」，
 * 而不是假装能精确到百分比。
 *
 * ## 字段集对齐 `QueueMonitor` 实际读的字段
 */

import type { SourceV } from '@/lib/api/sources'

import { KIND_LABELS } from '../../sources/lib/sourceKind'

export interface QueueRowItem {
  id: number
  /** 资料名（后端 `title`）。 */
  name: string
  /** 类型标签，如「PDF」「网页」「文稿」。 */
  kindLabel: string
  /** Material Symbol 名，由 `source_type` 派生。 */
  iconName: string
  /** 体积；URL 建源时后端没有 Content-Length，为 null。 */
  size: string | null
  /** 当前阶段的中文说明，如「正在切片」。 */
  progressLabel: string
  /**
   * 阶段名（中文短词，如「切片」），显示在行尾徽章的位置。
   * 与 `progressLabel` 分开是因为前者要短（徽章窄），后者带切片数。
   */
  stageLabel: string
  done: boolean
  failed: boolean
  /** 失败原因。后端 `error_message`，成功时为 null。 */
  error: string | null
  chunkCount: number
}

/**
 * `source_type` → 展示标签 + 图标名。
 *
 * 标签沿用设计稿原词（`PDF` / `Web HTML`）；`text` 那类设计稿没有对应
 * 条目（它列的是 Audio / Voice 与 Excel / Sheet，后端不支持），这里用
 * 中性的「文稿」——不改成更「规范」的措辞，用户看的是这份稿子。
 */
// 标签与图标与资料库页共用一份（sources/lib/sourceKind.ts）——
// 之前两边各一份 Record，改 docx 的措辞时不会报错，实测同一份资料在
// 资料库显示「DOCX」、在这里显示「Word」。
const KIND = Object.fromEntries(
  (Object.keys(KIND_LABELS) as (keyof typeof KIND_LABELS)[]).map((type) => [
    type,
    { label: KIND_LABELS[type].queueLabel, icon: KIND_LABELS[type].icon },
  ]),
) as Record<SourceV['source_type'], { label: string; icon: string }>

/**
 * 后端 6 态 → 两段中文文案。
 *
 * `label` 是「在做什么」，进 meta 行（带切片数）；
 * `short` 是徽章里的短词，进行尾。分开是因为徽章宽度只够两三个字，
 * 而「正在切片中」放进徽章会换行。
 *
 * 文案不是状态名的直译——`pending` 叫「排队中」而不是「待处理」，
 * 因为用户关心的是「它什么时候动」，不是它在数据库里叫什么。
 */
const STAGE: Record<SourceV['status'], { label: string; short: string }> = {
  pending: { label: '排队中', short: '排队中' },
  parsing: { label: '正在解析正文', short: '解析中' },
  chunking: { label: '正在切片', short: '切片中' },
  embedding: { label: '正在向量化', short: '向量化' },
  indexed: { label: '已索引至向量数据库', short: '已索引' },
  failed: { label: '摄取失败', short: '失败' },
}

/** 字节 → 人类可读。与 sources 页同一套 1000 进制。 */
export function formatBytes(bytes: number | null): string | null {
  if (bytes === null) return null
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

/** 已有切片数与后端 `chunk_count` 一致；索引完成前就是 0。 */
export function chunkLabel(count: number): string {
  return count === 0 ? '尚未产出切片' : `${count} 个切片`
}

export function toQueueRow(source: SourceV): QueueRowItem {
  const failed = source.status === 'failed'
  const meta = STAGE[source.status]
  return {
    id: source.id,
    name: source.title,
    kindLabel: KIND[source.source_type].label,
    iconName: KIND[source.source_type].icon,
    size: formatBytes(source.size_bytes),
    // 失败时**不带切片数**：失败后 chunk_count 是上一次成功写入的值，
    // 「N 个切片」配着红色失败徽章会自相矛盾。原因只出现在 error 字段里。
    progressLabel: failed ? meta.label : `${meta.label} · ${chunkLabel(source.chunk_count)}`,
    stageLabel: meta.short,
    done: source.status === 'indexed',
    failed,
    error: failed ? (source.error_message ?? '摄取失败') : null,
    chunkCount: source.chunk_count,
  }
}
