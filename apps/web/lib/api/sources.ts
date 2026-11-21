/**
 * 资料 / 切片接口的前端镜像。
 *
 * 字段对齐后端 `apps/api/app/schemas/source.py` 的 `SourceResponse` 与
 * `ChunkResponse`——改了那边必须同步改这里。
 */

import { API_BASE, ApiError, apiFetch } from './client'

/** 资料类型。与后端 `SourceType`（`'pdf' | 'html' | 'text' | 'docx'`）一一对应。 */
export type SourceTypeV = 'pdf' | 'html' | 'text' | 'docx'

/**
 * 摄取状态。与后端 `SourceStatus` 一一对应（6 态）。
 *
 * ⚠️ 这是**存储态**，不是表格用的展示态（3 态）——两者的映射在
 * `sources/lib/sourceTypes.ts` 的 `toRowStatus`。
 */
export type SourceStatusV = 'pending' | 'parsing' | 'chunking' | 'embedding' | 'indexed' | 'failed'

/** 一份资料。与后端 `SourceResponse` 一一对应。 */
export interface SourceV {
  id: number
  title: string
  source_type: SourceTypeV
  status: SourceStatusV
  /** URL 建源时的原始地址；上传文件建源为 null。 */
  url: string | null
  /** `size_bytes` 为 null（URL 建源时后端没抓到 Content-Length）。 */
  size_bytes: number | null
  chunk_count: number
  /** 解析出的纯文本长度（`char_count`）。 */
  char_count: number
  /** 资料可信度评分 0–1。 */
  credibility_score: number
  /** 失败原因，仅 `status === 'failed'` 时非空。 */
  error_message: string | null
  created_at: string
  /** 被多少份报告引用过（按报告去重）。 */
  citation_count: number
  /**
   * 逻辑文档组 id。null = 不参与分组（公开来源、未归组资料）。
   *
   * 同一份资料的多个版本（改过的简历）共享同一个 group_id，
   * 组内至多一份 `is_active` 为 true——那份才是参与检索的**生效版本**。
   */
  group_id: number | null
  /** 组内版本号，从 1 起。 */
  version_no: number
  /**
   * 是否是组内生效版本。false = 归档的旧版（留档但不进默认检索）。
   *
   * 归档版本仍可手动切回生效——见 `activateSource`。
   */
  is_active: boolean
  /**
   * 给人看的版本标记，如「第 2 版」。
   *
   * **空串 = 没有值得显示的版本信息**——不参与分组，或它是该组的第 1 版。
   * 第 1 版不标是因为每份上传的资料都自建一个组，标了会让表格每行都挂
   * 一个不携带信息的徽章。
   *
   * **由后端算好**：拼法要跟「什么算一组」保持一致，两处各拼一次
   * 必然漂移。
   */
  version_label: string
}

/** 资料列表响应。与后端 `SourceListResponse` 一一对应。 */
export interface SourceListV {
  items: SourceV[]
  total: number
}

/** 列出当前用户的全部资料。后端无分页参数，一次返回全部。 */
export function fetchSources(signal?: AbortSignal): Promise<SourceListV> {
  return apiFetch<SourceListV>('/api/v1/sources', { signal })
}

/** 删一份资料。返回 204。 */
export function deleteSource(sourceId: number): Promise<void> {
  return apiFetch<void>(`/api/v1/sources/${sourceId}`, { method: 'DELETE' })
}

/**
 * 把某份资料设为其所在组的**生效版本**。
 *
 * 同一份资料有多个版本时，默认只有生效版本参与本地检索与引用。
 * 用户可以在资料页手动切换——比如刚上传了一份旧版想拿它当准，
 * 或者想回退到之前那版。
 *
 * 成功后同组的其他版本自动转归档（留档但不进检索）。
 */
export function activateSource(sourceId: number, signal?: AbortSignal): Promise<SourceV> {
  return apiFetch<SourceV>(`/api/v1/sources/${sourceId}/activate`, {
    method: 'PATCH',
    ...(signal ? { signal } : {}),
  })
}

/** 从错误响应体里取 `detail`。422 时它是**数组**（字段级校验），拼成人话。 */
async function detailOf(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string | { msg?: string }[] }
    const d = body.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d))
      return d
        .map((x) => x.msg ?? '')
        .filter(Boolean)
        .join('；')
  } catch {
    // 响应体不是 JSON（网关的 HTML 错误页），走下面的兜底文案
  }
  return `请求失败（${res.status}）`
}

/**
 * 上传一个文件建源。
 *
 * 用裸 `fetch` 而不是 `apiFetch`：后者按 `Content-Type: application/json`
 * 发请求体，而这里必须是浏览器自己带 boundary 的 `multipart/form-data`。
 * 手写 `Content-Type` 反而会让 boundary 丢掉，服务端解析失败。
 *
 * 立刻返回 201 + `status: "pending"`——摄取是后台任务，前端要拿 `id`
 * 去轮询 `fetchSource`，不能等它跑完。
 */
export async function uploadSource(file: File, signal?: AbortSignal): Promise<SourceV> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE}/api/v1/sources`, {
    method: 'POST',
    credentials: 'include',
    body: form,
    ...(signal ? { signal } : {}),
  })
  if (!res.ok) {
    throw new ApiError(res.status, await detailOf(res))
  }
  return (await res.json()) as SourceV
}

/**
 * URL 建源。**`title` 是必填**（后端 `SourceCreate.title` 有 min_length=1），
 * 所以 UI 必须能提供——add-sources 页从 URL 末段推导并允许改。
 */
export function createSourceFromUrl(
  body: { title: string; url: string; source_type: SourceTypeV },
  signal?: AbortSignal,
): Promise<SourceV> {
  return apiFetch<SourceV>('/api/v1/sources/url', {
    method: 'POST',
    body: JSON.stringify(body),
    ...(signal ? { signal } : {}),
  })
}

/** 查单份资料的状态。**摄取进度轮询用的就是它**（后端 docstring 明写）。 */
export function fetchSource(sourceId: number, signal?: AbortSignal): Promise<SourceV> {
  return apiFetch<SourceV>(`/api/v1/sources/${sourceId}`, { signal })
}

/** 切片详情。与后端 `ChunkResponse` 一一对应。 */
export interface Chunk {
  id: number
  /** 该片在这份资料里的序号，0 起。 */
  chunk_index: number
  content: string
  /**
   * 页序（1 起）；null = 没有分页概念的资料（网页）。
   *
   * 纯文本**也可能有值**：parser 按 `\f`（换页符）切段并从 1 编号。
   * 所以它不是「PDF 专属字段」，而是「原文里第几段」。
   */
  page: number | null
  /** 切片在原始文本里的字符区间 [start, end)。 */
  start_offset: number
  end_offset: number
}

/**
 * 资料切片的进程内缓存。sourceId → 该资料的全量切片。
 *
 * ## 为什么需要它
 *
 * 后端没有「按 chunk_id 取单片」的端点，只能拉全量再在前端筛。一份资料
 * 的切片数与文件大小成正比（CHUNK_SIZE=512 字符），单次响应可达上百 MB。
 * 同一份报告里点 3 个角标 = 3 次全量往返，且每次都要在主线程 `res.json()`
 * 解析一遍。缓存把这个降到 1 次。
 *
 * ## 什么时候必须清
 *
 * **登出。** logout 走的是 `router.push` 客户端导航，不重载模块，
 * 模块级 Map 原样存活——上一个用户的私有资料全文会留在 JS 堆里，
 * 而下一次命中缓存连一次带鉴权的请求都不发，「资料已删除」也感知不到。
 * argus 的整个前提就是「私有资料」，所以登出时清是硬要求，不是优化。
 *
 * ## 什么时候可以不清
 *
 * 重新提问时清（见 `clearChunkCache` 的调用点）：资料被重传后 chunk_id 会
 * 变，但缓存里存的是旧 id，`find` 返回 undefined，落到「该切片已不存在」
 * 的错误分支——这是对的，报告里的引用确实已经失效。
 *
 * ## 内存上界
 *
 * **没有上界，这是已知的取舍。** 上限内的一个 50MB `.txt` 能切出十万多片，
 * parsed 后常驻百 MB 级；多份资料叠加更糟，移动端 Safari 上足以让标签页 OOM。
 * 根治要补 `GET /sources/{id}/chunks/{chunk_id}`（后端路由改动）。
 * 在那之前，至少该按累计字符数截断——但那会让缓存行为变得不可预测
 * （用户不知道自己的引用还准不准），所以先不做，等有真实 OOM 反馈再说。
 */
const chunkCache = new Map<number, Chunk[]>()

/**
 * 列出某份资料的全部切片（带缓存）。
 *
 * 先补全量再筛是后端缺单片端点下的次优解。真要根治要补
 * `GET /sources/{id}/chunks/{chunk_id}`，那需要动后端路由。
 */
export async function fetchChunks(sourceId: number, signal?: AbortSignal): Promise<Chunk[]> {
  const cached = chunkCache.get(sourceId)
  if (cached) return cached

  const chunks = await apiFetch<Chunk[]>(`/api/v1/sources/${sourceId}/chunks`, { signal })
  chunkCache.set(sourceId, chunks)
  return chunks
}

/** 提问开始时清缓存——上一轮的资料可能已被重摄取。 */
export function clearChunkCache(): void {
  chunkCache.clear()
}
