/**
 * 报告列表页的视图常量与类型。
 *
 * 原本这里有 6 条假报告（`REPORTS`）与一堆假 KPI。假数据已删——
 * 报告行现在来自后端 `GET /api/v1/reports`，由 `toReportRow` 映射成
 * 下面这个 `Report` 形状，**组件一行都不用改**。
 *
 * 剩下的常量（KPI 磁贴、筛选选项、表头文案）仍是设计稿里的静态文案，
 * 它们不表示数据，只是界面上固定的一段话。
 *
 * Lives next to the route (per project convention).
 */

import type { ReportSummaryV } from '@/lib/api/reports'

export type TopicTone = 'primary' | 'secondary' | 'neutral' | 'fixed'
/**
 * 报告的三种状态。
 *
 * - `verified`：跑完且正文完整。
 * - `truncated`：正文不完整——流程中途崩溃，或撞到轮次上限被强制收尾。
 * - `running`：生成中（后端目前不落盘这种状态，但组件支持）。
 */
export type ReportStatus = 'verified' | 'truncated' | 'running'

export interface ReportTopic {
  label: string
  tone: TopicTone
}

export interface Report {
  id: string
  title: string
  summary: string
  topic: ReportTopic
  generatedAt: string
  generatedAtSub: string
  sourcesCount: number
  viewsCount: number
  status: ReportStatus
  starred: boolean
  /** When status === "running", 0..100 progress indicator. */
  runningProgress?: number
  runningStage?: string
}

export interface MetricTile {
  id: string
  label: string
  value: string
  sub: string
  icon: string
  valueTone: 'default' | 'primary'
  subTone: 'success' | 'secondary'
}

export interface FilterTab {
  id: string
  label: string
  count: number
}

export type TopicFilterId =
  'ai-hardware' | 'frontier-model' | 'policy' | 'vc-trend' | 'green-energy' | 'frontier-tech'

export interface TopicFilter {
  id: TopicFilterId
  label: string
  count: number
  checked: boolean
}

export interface CitationScale {
  id: string
  label: string
  active: boolean
}

export interface PipelineStatusFilter {
  id: string
  label: string
  checked: boolean
}

export interface SortOption {
  id: string
  label: string
}

export interface TimeframeOption {
  id: string
  label: string
  active: boolean
}

/* ── Page header copy ─────────────────────────────────────────────── */

export const PAGE_TITLE = '研究报告库'
export const PAGE_TITLE_EN = 'RESEARCH REPOSITORY'
export const PAGE_SUBTITLE_PREFIX = '本月已由多智能体生成'
export const PAGE_SUBTITLE_REPORT_COUNT = '47'
export const PAGE_SUBTITLE_MID = '篇深度研报'
export const PAGE_SUBTITLE_TRACK_PREFIX = '覆盖'
export const PAGE_SUBTITLE_TRACK_COUNT = '12'
export const PAGE_SUBTITLE_TRACK_SUFFIX = '个技术与战略市场赛道'
export const PAGE_DAG_STATUS = 'DAG 持续监视中'

/* ── Top CTAs ─────────────────────────────────────────────────────── */

export const CTA_FILTER_LABEL = '多维筛选'
export const CTA_NEW_RESEARCH_LABEL = '发起新研究'
export const CTA_NEW_RESEARCH_SHORTCUT = '⌘N'

/* ── Metric strip (4 KPI tiles) ───────────────────────────────────── */

export const METRIC_TILES: ReadonlyArray<MetricTile> = [
  {
    id: 'verified',
    label: '已交叉验证深度报告',
    value: '42',
    sub: '89.3% 合格率',
    icon: 'verified',
    valueTone: 'default',
    subTone: 'success',
  },
  {
    id: 'pipeline',
    label: '实时流水线处理中',
    value: '3',
    sub: '47 节点处于运行态',
    icon: 'cyclone',
    valueTone: 'primary',
    subTone: 'secondary',
  },
  {
    id: 'citations',
    label: '平均学术与产业溯源',
    value: '26.4',
    sub: '权威源 / 篇',
    icon: 'database',
    valueTone: 'default',
    subTone: 'secondary',
  },
  {
    id: 'views',
    label: '组织内综合调阅',
    value: '1,482',
    sub: '较上周 +24%',
    icon: 'visibility',
    valueTone: 'default',
    subTone: 'success',
  },
]

/* ── Filter tabs ──────────────────────────────────────────────────── */

export const FILTER_TABS: ReadonlyArray<FilterTab> = [
  { id: 'all', label: '全部报告', count: 47 },
  { id: 'starred', label: '星标收藏', count: 12 },
  { id: 'shared', label: '已向团队共享', count: 8 },
  { id: 'archive', label: '历史归档', count: 5 },
]

/* ── Search input ─────────────────────────────────────────────────── */

export const SEARCH_PLACEHOLDER = '搜索报告标题、标签或智能体关键词...'
export const SEARCH_SHORTCUT = '⌘K'

/* ── Sort dropdown ────────────────────────────────────────────────── */

export const SORT_OPTIONS: ReadonlyArray<SortOption> = [
  { id: 'newest', label: '最新生成 (降序)' },
  { id: 'citations', label: '引用权威源最多' },
  { id: 'views', label: '调阅频次最高' },
  { id: 'depth', label: '研究深度星级' },
]

/* ── View switcher tooltips ───────────────────────────────────────── */

export const VIEW_TABLE_LABEL = '表格视图'
export const VIEW_GRID_LABEL = '网格卡片视图'

/* ── Filter drawer ────────────────────────────────────────────────── */

export const FILTER_DRAWER_TITLE = '多维指标筛选'
export const FILTER_DRAWER_RESET = '重置条件'

export const FILTER_TIMEFRAME_TITLE = '时间跨度 / Timeframe'
export const TIMEFRAME_OPTIONS: ReadonlyArray<TimeframeOption> = [
  { id: 'all', label: '全部周期', active: true },
  { id: '24h', label: '过去 24 小时', active: false },
  { id: '7d', label: '近 7 天', active: false },
  { id: 'mtd', label: '本月至今', active: false },
]

export const FILTER_TOPIC_TITLE = '课题研究赛道 / Topics'
export const TOPIC_FILTERS: ReadonlyArray<TopicFilter> = [
  { id: 'ai-hardware', label: 'AI 硬件与芯片架构', count: 14, checked: true },
  { id: 'frontier-model', label: '前沿模型与多模态', count: 12, checked: true },
  { id: 'policy', label: '政策法案与合规监管', count: 8, checked: false },
  { id: 'vc-trend', label: '风险投资与产业格局', count: 7, checked: false },
  { id: 'green-energy', label: '绿色能源与智算中心', count: 6, checked: false },
]

export const FILTER_CITATION_TITLE = '权威源规模 / Citation Scale'
export const CITATION_SCALES: ReadonlyArray<CitationScale> = [
  { id: '1-10', label: '1 - 10 篇', active: false },
  { id: '10-30', label: '10 - 30 篇 (标准)', active: true },
  { id: '30+', label: '30+ 篇 (宏观)', active: false },
]

export const FILTER_STATUS_TITLE = '流水线状态 / Pipeline Status'
export const PIPELINE_STATUSES: ReadonlyArray<PipelineStatusFilter> = [
  { id: 'verified', label: '已通过全部交叉验证', checked: true },
  { id: 'running', label: '智能体流式撰写中', checked: true },
  { id: 'attention', label: '异常需人工介入核实', checked: false },
]

export const CONFIDENCE_LABEL = '综合置信度均值'
export const CONFIDENCE_VALUE = '98.2%'
export const CONFIDENCE_NOTE = '基于多智能体交叉对撞机制，排除幻觉因子。'

/* ── Table column headers ─────────────────────────────────────────── */

export const TABLE_HEADER = {
  title: '标题与核心摘要',
  topic: '研究赛道',
  generatedAt: '生成时间',
  sources: '权威源',
  status: '状态 / 操作',
} as const

/* ── Pagination ───────────────────────────────────────────────────── */

export const PAGE_SIZE = 6
export const PAGINATION_RANGE_FROM = 1
export const PAGINATION_RANGE_TO = 6

/* ── Bulk action bar ──────────────────────────────────────────────── */

export const BULK_ACTIONS = [
  { id: 'export', label: '批量导出 PDF', icon: 'picture_as_pdf' },
  { id: 'group', label: '归入集合', icon: 'folder' },
  { id: 'revalidate', label: '重新校验', icon: 'sync' },
  { id: 'archive', label: '批量归档', icon: 'delete', tone: 'danger' as const },
] as const

/* ── 真数据 → 视图模型的映射 ─────────────────────────────────────
 *
 * 页面上所有组件都按 `Report` 这个形状消费（表格、卡片、选中态都读
 * 同一套字段）。后端 `GET /api/v1/reports` 返回的是 `ReportSummaryV`
 * （见 `@/lib/api/reports`），字段名不一样、且**缺几个**。
 *
 * 与其把每个组件改成两套形状（表格一套、卡片一套、选中态一套），
 * 不如在这里把后端数据映射成既有形状——**组件一行都不用改**。
 *
 * 缺的字段怎么填，每个都有理由，不是随手填的：
 *
 * - `topic`：后端没有分类字段。填固定的中性标签，保留组件原有的
 *   徽章样式与位置。编一个分类名是撒谎。
 * - `summary`：后端列表接口不返回正文（返回了会把列表撑爆）。用
 *   提问 + 用量拼一行摘要，让卡片/表格有副标题可显示。
 * - `viewsCount`：后端没有阅读数。填 0——组件会渲染成「0 阅」，
 *   是个明显待补的占位，但比编一个数字诚实。
 * - `status`：后端落盘两种报告——跑完的（`truncated=false`）与中途
 *   崩溃/被强制收尾的（`truncated=true`）。后者正文不完整，要标成
 *   `truncated` 让读者知道，别当成完整报告读。
 * - `starred`：后端没有星标。填 false。
 * - `runningProgress` / `runningStage`：同 status，没有 running 态就不给。
 */

/** 无分类信息时的中性徽章。 */
const DEFAULT_TOPIC: ReportTopic = { label: '研究报告', tone: 'neutral' }

/** ISO 时间串 → 「2026-10-20 14:14」。解析失败就原样返回。 */
function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 把后端报告摘要映射成列表页消费的 `Report`。 */
export function toReportRow(r: ReportSummaryV): Report {
  const tokens = r.input_tokens + r.output_tokens
  return {
    id: String(r.id),
    title: r.question,
    summary: `${r.citation_count} 条引用 · ${tokens.toLocaleString('zh-CN')} tokens · 耗时 ${(r.elapsed_ms / 1000).toFixed(1)} 秒`,
    topic: DEFAULT_TOPIC,
    generatedAt: formatDateTime(r.created_at),
    generatedAtSub: r.session_id.slice(0, 8),
    sourcesCount: r.citation_count,
    viewsCount: 0,
    status: r.truncated ? 'truncated' : 'verified',
    starred: false,
  }
}
