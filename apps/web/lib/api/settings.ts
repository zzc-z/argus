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

/* ── 用户凭据配置 ───────────────────────────────────────────── */

/**
 * 一项凭据的状态。**不含密钥内容**——后端只报「配了没有」与「来自哪一层」。
 *
 * 与后端 `apps/api/app/schemas/credentials.py` 的 `CredentialItem` 一一对应。
 */
export interface CredentialItemV {
  /** 最终生效的值存在吗。 */
  configured: boolean
  /** 值来自哪一层：'user'（用户自己配的）/ 'env'（部署默认）/ 'none'（都没有）。 */
  source: 'user' | 'env' | 'none'
}

/** 凭据配置的完整状态。与后端 `CredentialsResponse` 一一对应。 */
export interface CredentialsV {
  anthropic_api_key: CredentialItemV
  anthropic_base_url: CredentialItemV
  tavily_api_key: CredentialItemV
  embedding_api_key: CredentialItemV
  embedding_base_url: CredentialItemV
  /** 复杂任务的模型名（Researcher / Writer / Critic）。 */
  /** 当前生效的 Anthropic 中转站地址。**不是密钥**，所以直接回显。 */
  anthropic_base_url_value: string | null
  /** 当前生效的嵌入服务端点。**不是密钥**，所以直接回显。 */
  embedding_base_url_value: string | null
  /** 复杂任务的模型名（Researcher / Writer / Critic）。 */
  anthropic_complex_model: string
  /** 简单任务的模型名（Supervisor / Analyst / Summarizer）。 */
  anthropic_default_model: string
  /** Critic（引用忠实度判定）的模型名。 */
  anthropic_critic_model: string
  /** 嵌入模型名。**部署级，用户不能改**——向量索引全库共享且维度写死。 */
  embedding_model: string
  /** Critic 与 Writer 是否同一个模型——同型号会有自偏好偏差风险。 */
  critic_equals_writer: boolean
}

/**
 * 要保存的凭据。**部分更新**——三种状态要分清：
 *
 * - 字段**缺省**（不在对象里）= 不改
 * - `''` = 忽略（用户没动这个输入框）
 * - `null` = 清空（回落到部署默认）
 *
 * `undefined` 与「键不存在」在这里是同一件事——用 `Partial` + 显式
 * `null` 表达「清空」。
 */
export interface CredentialsUpdate {
  anthropic_api_key?: string | null
  anthropic_base_url?: string | null
  tavily_api_key?: string | null
  embedding_api_key?: string | null
  embedding_base_url?: string | null
  anthropic_complex_model?: string | null
  anthropic_default_model?: string | null
  anthropic_critic_model?: string | null
}

/**
 * 取当前用户的凭据配置状态。
 *
 * 鉴权走 `argus_session` cookie（`apiFetch` 已带 `credentials: 'include'`）。
 */
export function fetchCredentials(signal?: AbortSignal): Promise<CredentialsV> {
  return apiFetch<CredentialsV>('/api/v1/settings/credentials', { signal })
}

/**
 * 保存凭据配置。返回保存**之后**的状态——用户不用再拉一次。
 */
export function saveCredentials(payload: CredentialsUpdate): Promise<CredentialsV> {
  return apiFetch<CredentialsV>('/api/v1/settings/credentials', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}
