/**
 * 报告接口的前端镜像。
 *
 * 字段对齐后端 `apps/api/app/schemas/report.py` 的 `ReportSummaryV` /
 * `ReportDetailV` / `ReportCitationV`——改了那边必须同步改这里。
 *
 * ## 与 explore 的引用类型的关系
 *
 * `ReportCitationV` 比 explore 的 `ReferenceV`（`lib/api/sse.ts`）**少一个
 * `recall`**：那是检索召回来源（'向量+BM25' / '向量' / 'BM25'），只在那次
 * 流里有意义——历史报告里没有当时的检索现场。所以两边的引用不能直接
 * 互换类型，角标渲染要能接受 `recall` 缺失。
 */

import { apiFetch } from './client'

/** 报告引用的一个切片。与后端 `ReportCitationV` 一一对应。 */
export interface ReportCitationV {
  /** 角标编号，从 1 起，与正文里的 `[n]` 一一对应。 */
  n: number
  chunk_id: number
  source_id: number
  /** 0-based，展示时是「第 n+1 块」。 */
  chunk_index: number
  /** PDF 页码；null = 非 PDF。 */
  page: number | null
  /** 资料名。资料改名后历史报告会跟着变——那是对的。 */
  title: string
  /** 切片前 120 字。 */
  excerpt: string
  /** 该切片在这份报告里被引用了几次。 */
  cite_count: number
}

/** 报告摘要。列表页用——不含正文。 */
export interface ReportSummaryV {
  id: number
  /** 原始提问。报告的「标题」就是这个——后端不另存标题。 */
  question: string
  session_id: string
  input_tokens: number
  output_tokens: number
  elapsed_ms: number
  created_at: string
  /**
   * 这份报告是否被截断——正文不完整。
   *
   * 两种情况会置 true：流程中途崩溃（正文已生成但没跑完），或者撞到
   * 轮次上限被强制收尾。列表页要标出来，否则读者会当成完整报告。
   */
  truncated: boolean
  /**
   * 这份报告引用了多少个**切片**。
   *
   * 是切片数不是资料数——一份报告引同一份资料的 5 个切片算 5。
   * 后端用标量子查询算出来（避免列表页 N+1）。
   */
  citation_count: number
}

/** 报告详情。多了正文与引用表。 */
export interface ReportDetailV extends ReportSummaryV {
  /** 正文 markdown 原文。 */
  content: string
  citations: ReportCitationV[]
}

/** 报告列表响应。`total` 是全量计数（不是本页条数）。 */
export interface ReportListV {
  items: ReportSummaryV[]
  total: number
  limit: number
  offset: number
}

/** 列出我的报告。后端默认 limit=20，按创建时间倒序。 */
export function fetchReports(
  params: { limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<ReportListV> {
  const q = new URLSearchParams()
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const suffix = q.toString() ? `?${q}` : ''
  return apiFetch<ReportListV>(`/api/v1/reports${suffix}`, { signal })
}

/** 取单份报告。仅限报告所有者——别人的 id 会 404。 */
export function fetchReport(reportId: number, signal?: AbortSignal): Promise<ReportDetailV> {
  return apiFetch<ReportDetailV>(`/api/v1/reports/${reportId}`, { signal })
}

/** 删一份报告。返回 204。 */
export function deleteReport(reportId: number): Promise<void> {
  return apiFetch<void>(`/api/v1/reports/${reportId}`, { method: 'DELETE' })
}
