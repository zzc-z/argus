/**
 * Dashboard 概览与系统状态接口的前端镜像。
 *
 * 字段对齐后端 `apps/api/app/schemas/dashboard.py` 的 `DashboardResponse` /
 * `SettingsStatusResponse`——改了那边必须同步改这里。
 *
 * 两个接口都是**按当前登录用户**聚合的（后端按 `user_id` 过滤），
 * 所以这里的数字都是「我的」，不是全站的。
 */

import { apiFetch } from './client'
import type { ReportSummaryV } from './reports'

/**
 * 最近报告列表项。
 *
 * 直接复用 `ReportSummaryV`——后端 `DashboardResponse.recent_reports` 里
 * 装的就是这个模型（`apps/api/app/schemas/report.py`），字段完全一致，
 * 不必再抄一份。
 */
export type DashboardReportV = ReportSummaryV

/** Dashboard 概览。全部是当前用户的聚合值。 */
export interface DashboardV {
  /** 我的报告数。 */
  report_count: number
  /** 我的资料数。 */
  source_count: number
  /** 我的资料切出来的切片总数。 */
  chunk_count: number
  /** 所有报告的累计输入 token。 */
  total_input_tokens: number
  /** 所有报告的累计输出 token。 */
  total_output_tokens: number
  /** 最近生成的报告，按时间倒序（后端最多给 5 条）。 */
  recent_reports: DashboardReportV[]
  /** 最后一篇报告的生成时间；一篇都没有时为 null。 */
  latest_report_at: string | null
}

/** 一个外部能力的配置状态——只说「配了没有」，不含任何密钥内容。 */
export interface ProviderStatusV {
  id: string
  name: string
  configured: boolean
  /** 一句话说明，如「未配置 API 密钥」。 */
  detail: string
}

/** 向量索引规模。 */
export interface VectorIndexV {
  source_count: number
  chunk_count: number
  /** 已完成向量化的切片数。 */
  embedded_chunk_count: number
}

/** 系统状态响应。 */
export interface SettingsStatusV {
  providers: ProviderStatusV[]
  vector_index: VectorIndexV
}

/** Dashboard 概览。 */
export function fetchDashboard(signal?: AbortSignal): Promise<DashboardV> {
  return apiFetch<DashboardV>('/api/v1/dashboard', { signal })
}

/**
 * 系统状态：外部能力配置 + 向量索引规模。
 *
 * 鉴权同 `/dashboard`（后端按 `user_id` 统计索引规模）。
 */
export function fetchSettingsStatus(signal?: AbortSignal): Promise<SettingsStatusV> {
  return apiFetch<SettingsStatusV>('/api/v1/settings/status', { signal })
}
