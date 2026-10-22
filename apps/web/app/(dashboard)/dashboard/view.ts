/**
 * Dashboard 视图层：后端响应 → 组件消费的形状。
 *
 * 原先这里放的是整页假数据（`KPIS` / `ACTIVITIES` / `SUBSCRIPTIONS` /
 * `REPORTS`）——已删。现在每个数字都来自
 * `GET /api/v1/dashboard` 与 `GET /api/v1/settings/status`
 * （见 `@/lib/api/dashboard`），由本文件的映射函数转成组件要的形状。
 *
 * 剩下的都是**静态文案**与**类型定义**——它们不表示数据。
 */

import type { DashboardV, SettingsStatusV } from '@/lib/api/dashboard'
import type { ReportSummaryV } from '@/lib/api/reports'

/* ── 组件消费的类型 ─────────────────────────────────────────────── */

export type FooterIconTone = 'success' | 'primary' | 'secondary'
export type ActivityBadgeTone = 'highlight' | 'muted' | 'plain' | 'warning'
export type ActivityIconBox = 'primary' | 'default' | 'accent'

export interface Kpi {
  id: string
  label: string
  icon: string
  value: string
  sub: string
  footerIcon: string
  footerIconTone: FooterIconTone
  footerPrefix: string
  footerHighlight: string
  footerSuffix: string
  /**
   * 0-100，渲染卡片底部的进度条。
   *
   * **缺省就不画进度条**：后端没有「配额」概念，只有能算出来的比例
   * （如向量化完成率）才给这个值——没有就留空，不编数字。
   */
  progress?: number
}

export interface ActivityItem {
  id: string
  icon: string
  iconBox: ActivityIconBox
  title: string
  meta: string
  badgeText: string
  badgeTone: ActivityBadgeTone
  timestamp: string
  /** 最新一条：紫色高亮 + 1px inset 描边。 */
  highlight?: boolean
}

export interface ExploreReport {
  /** 后端报告 id（数字）——`/report/{id}` 的链接目标。 */
  id: number
  /** 报告标题 = 原始提问。 */
  title: string
  /** 相对时间，如「2 小时前」。 */
  activity: string
  /** 引用了多少个切片。 */
  citations: number
  /** 耗时，如「12.3 秒」。 */
  elapsed: string
  inputTokens: number
  outputTokens: number
  /** 会话 id 前 8 位——用来把卡片和运行实例对上。 */
  sessionShort: string
  /** 封面上的装饰图标（Material Symbols 名）。 */
  coverIcon: string
}

/* ── 文案常量 ───────────────────────────────────────────────────── */

export const GREETING = '欢迎回来'

export const KPI_LABELS = {
  reports: '我的报告',
  sources: '我的资料',
  chunks: '检索切片',
  tokens: '累计 Token',
} as const

export const KPI_SUBS = {
  reports: '篇已生成',
  sources: '份资料',
  chunks: '个可检索片段',
  tokens: '输入 + 输出',
} as const

export const ACTIVITY_ICON = 'article'

/** 封面上的装饰图标——报告没有自己的封面图，用一个通用图标。 */
export const EXPLORE_COVER_ICON = 'description'

/* ── 映射函数 ───────────────────────────────────────────────────── */

/**
 * KPI 磁贴。
 *
 * 四张卡对应后端的四个聚合值：报告数 / 资料数 / 切片数 / 累计 token。
 * 只有「检索切片」那张有进度条——向量化的完成率能从
 * `settings/status` 的 `embedded_chunk_count / chunk_count` 算出来。
 */
export function toKpis(dashboard: DashboardV, settings: SettingsStatusV | null): Kpi[] {
  const totalTokens = dashboard.total_input_tokens + dashboard.total_output_tokens
  const embedded = settings?.vector_index.embedded_chunk_count ?? null
  const chunkTotal = dashboard.chunk_count
  const progress =
    embedded !== null && chunkTotal > 0
      ? Math.min(100, Math.round((embedded / chunkTotal) * 100))
      : undefined

  return [
    {
      id: 'reports',
      label: KPI_LABELS.reports,
      icon: 'auto_stories',
      value: formatNumber(dashboard.report_count),
      sub: KPI_SUBS.reports,
      footerIcon: 'verified',
      footerIconTone: 'primary',
      footerPrefix: '最近一篇 ',
      footerHighlight: dashboard.latest_report_at
        ? formatRelative(dashboard.latest_report_at)
        : '暂无',
      footerSuffix: ' 生成',
    },
    {
      id: 'sources',
      label: KPI_LABELS.sources,
      icon: 'database',
      value: formatNumber(dashboard.source_count),
      sub: KPI_SUBS.sources,
      footerIcon: 'database',
      footerIconTone: 'secondary',
      footerPrefix: '外部能力 ',
      footerHighlight: providerSummary(settings),
      footerSuffix: ' 已就绪',
    },
    {
      id: 'chunks',
      label: KPI_LABELS.chunks,
      icon: 'layers',
      value: formatNumber(chunkTotal),
      sub: KPI_SUBS.chunks,
      footerIcon: 'insights',
      footerIconTone: 'secondary',
      footerPrefix: '已向量化 ',
      footerHighlight: embedded === null ? '未知' : formatNumber(embedded),
      footerSuffix: ' 个',
      progress,
    },
    {
      id: 'tokens',
      label: KPI_LABELS.tokens,
      icon: 'bolt',
      value: formatNumber(totalTokens),
      sub: KPI_SUBS.tokens,
      footerIcon: 'bolt',
      footerIconTone: 'success',
      footerPrefix: '输入 ',
      footerHighlight: formatNumber(dashboard.total_input_tokens),
      footerSuffix: ` / 输出 ${formatNumber(dashboard.total_output_tokens)}`,
    },
  ]
}

/** 最近活动流——一条报告一条。 */
export function toActivities(reports: ReportSummaryV[]): ActivityItem[] {
  return reports.map((r, index) => ({
    id: String(r.id),
    icon: ACTIVITY_ICON,
    iconBox: index === 0 ? 'primary' : 'default',
    title: r.question,
    meta: `输入 ${formatNumber(r.input_tokens)} / 输出 ${formatNumber(r.output_tokens)} tokens · 耗时 ${formatElapsed(r.elapsed_ms)}`,
    badgeText: `${r.citation_count} 条引用`,
    badgeTone: index === 0 ? 'highlight' : 'muted',
    timestamp: formatRelative(r.created_at),
    highlight: index === 0,
  }))
}

/** 「继续您的研究探索」卡片。 */
export function toExploreReports(reports: ReportSummaryV[]): ExploreReport[] {
  return reports.map((r) => ({
    id: r.id,
    title: r.question,
    activity: formatRelative(r.created_at),
    citations: r.citation_count,
    elapsed: formatElapsed(r.elapsed_ms),
    inputTokens: r.input_tokens,
    outputTokens: r.output_tokens,
    sessionShort: r.session_id.slice(0, 8),
    coverIcon: EXPLORE_COVER_ICON,
  }))
}

/* ── 格式化 ─────────────────────────────────────────────────────── */

/** 千分位。 */
export function formatNumber(n: number): string {
  return n.toLocaleString('zh-CN')
}

/**
 * 当天日期 → 「2026年10月21日」。
 *
 * 页头 meta 行用它显示「今天」。不带时区转换——要的是用户本地日历上的
 * 那天，不是 UTC 的那天。
 */
export function formatToday(d: Date): string {
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

/**
 * ISO 时间串 → 相对时间（「2 小时前」）。
 *
 * 手写而不是用 `Intl.RelativeTimeFormat`——措辞与阈值在项目里是统一的
 * （见 `sources/lib/sourceTypes.ts` 的同名函数），手写反而一致。
 */
export function formatRelative(iso: string, now: Date = new Date()): string {
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
  return `${Math.floor(days / 30)} 个月前`
}

/** 耗时。毫秒保留整数，秒保留一位小数。 */
export function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '未知'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)} 秒`
}

/** 外部能力就绪情况，如「2/3」。 */
function providerSummary(settings: SettingsStatusV | null): string {
  if (!settings || settings.providers.length === 0) return '未知'
  const ready = settings.providers.filter((p) => p.configured).length
  return `${ready}/${settings.providers.length}`
}
