/**
 * 系统设置页的接口镜像。
 *
 * 字段对齐后端 `apps/api/app/schemas/dashboard.py` 的
 * `SettingsStatusResponse` / `ProviderStatusV` / `VectorIndexV`——
 * 改了那边必须同步改这里。
 *
 * 个人信息（`/api/v1/me`）不在这里：全局登录态 Provider
 * （`lib/auth/UserContext.tsx`）已经拉过一次并缓存了同一份数据，
 * 再拉一遍是重复请求。
 */

import { apiFetch } from './client'

/** 一个外部能力的配置状态。与后端 `ProviderStatusV` 一一对应。 */
export interface ProviderStatusV {
  /** 能力标识，如 'anthropic' / 'tavily' / 'embedding'。 */
  id: string
  /** 展示名，如 '模型服务 (Anthropic)'。 */
  name: string
  /** 配置是否就绪。false 表示缺密钥或后端不可用。 */
  configured: boolean
  /** 给人看的一句话说明，如 '已配置（经中转站 https://llmapi.pro）'。 */
  detail: string
}

/** 向量索引规模。与后端 `VectorIndexV` 一一对应。 */
export interface VectorIndexV {
  /** 资料数。 */
  source_count: number
  /** 切片总数。 */
  chunk_count: number
  /** 已完成向量化的切片数。 */
  embedded_chunk_count: number
}

/** 系统设置页的状态响应。 */
export interface SettingsStatusV {
  providers: ProviderStatusV[]
  vector_index: VectorIndexV
}

/**
 * 取系统状态：各外部能力的配置情况 + 向量索引规模。
 *
 * 鉴权走 `argus_session` cookie（`apiFetch` 已带 `credentials: 'include'`）。
 */
export function fetchSettingsStatus(signal?: AbortSignal): Promise<SettingsStatusV> {
  return apiFetch<SettingsStatusV>('/api/v1/settings/status', { signal })
}
